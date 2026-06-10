from __future__ import annotations

import abc
import asyncio
import json
from datetime import datetime, timezone

import structlog
from redis.exceptions import TimeoutError as RedisTimeoutError

from .models import LastError

logger = structlog.get_logger("account-opening-consumer")


class AgentConsumer(abc.ABC):
    STAGE_NAME: str = ""  # Subclasses must set this
    # Event types this consumer handles. The base loop ack-skips any event
    # whose type is not in this set BEFORE touching idempotency, so unrelated
    # events (e.g. application_submitted reaching the provisioning consumer)
    # never poison the per-stage idempotency key.
    EVENT_TYPES: frozenset[str] = frozenset()

    def __init__(
        self,
        redis,
        stream: str,
        group: str,
        consumer_name: str,
        block_ms: int = 5000,
        retry_delay: float = 1.0,
    ) -> None:
        self.redis = redis
        self.stream_name = stream
        self.consumer_group = group
        self.consumer_name = consumer_name
        self.block_ms = block_ms
        self.retry_delay = retry_delay
        self._repository = None

    async def setup(self) -> None:
        try:
            await self.redis.xgroup_create(
                name=self.stream_name,
                groupname=self.consumer_group,
                id="0-0",
                mkstream=True,
            )
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise
            logger.info("Consumer group already exists", group=self.consumer_group)

    @abc.abstractmethod
    async def process_event(self, event_data: dict, idempotency_key: str | None = None) -> None:
        ...

    def _derive_idempotency_key(self, application_id: str, attempt: int) -> str:
        """Derive idempotency key: {applicationId}:{stage}:{attempt}"""
        return f"{application_id}:{self.STAGE_NAME}:{attempt}"

    async def _is_already_processed(self, key: str) -> bool:
        """Check if idempotency key was already processed (Redis SET check)."""
        redis_key = f"processed:{self.consumer_group}:{key}"
        result = await self.redis.sismember(redis_key, key)
        return bool(result)

    async def _mark_processed(self, key: str) -> None:
        """Mark idempotency key as processed with 24h TTL."""
        redis_key = f"processed:{self.consumer_group}:{key}"
        await self.redis.sadd(redis_key, key)
        await self.redis.expire(redis_key, 86400)  # 24h TTL

    def _classify_error(self, exc: Exception, stage: str, attempt: int) -> LastError:
        """
        Classify exception into LastError with code, message, and retryability.
        Subclasses can override for stage-specific classification.
        """
        exc_str = str(exc).lower()
        
        if "timeout" in exc_str or "timed out" in exc_str:
            return LastError(
                stage=stage,
                code="timeout",
                message="The service is temporarily unavailable. You can retry this step.",
                retryable=True,
                occurredAt=datetime.now(timezone.utc),
                attempt=attempt,
            )
        
        if "403" in exc_str or "401" in exc_str or "unauthorized" in exc_str:
            return LastError(
                stage=stage,
                code="auth_error",
                message="Authentication error occurred. Please contact support.",
                retryable=False,
                occurredAt=datetime.now(timezone.utc),
                attempt=attempt,
            )
        
        if isinstance(exc, ValueError):
            return LastError(
                stage=stage,
                code="validation_error",
                message="Invalid data detected. Please review your application.",
                retryable=False,
                occurredAt=datetime.now(timezone.utc),
                attempt=attempt,
            )
        
        if "connection" in exc_str or "network" in exc_str:
            return LastError(
                stage=stage,
                code="connection_error",
                message="Network connectivity issue. You can retry this step.",
                retryable=True,
                occurredAt=datetime.now(timezone.utc),
                attempt=attempt,
            )
        
        # Default: unknown error, assume retryable
        return LastError(
            stage=stage,
            code="unknown_error",
            message="An unexpected error occurred. You can retry this step.",
            retryable=True,
            occurredAt=datetime.now(timezone.utc),
            attempt=attempt,
        )

    async def process_one(self) -> int:
        messages = await self.redis.xreadgroup(
            groupname=self.consumer_group,
            consumername=self.consumer_name,
            streams={self.stream_name: ">"},
            count=1,
            block=self.block_ms,
        )

        processed = 0
        if not messages:
            return processed

        for _, entries in messages:
            for message_id, fields in entries:
                event_data = self._decode_fields(fields)

                # Drop events not handled by this consumer BEFORE deriving any
                # idempotency state. Without this filter, the base loop would
                # mark the per-stage idempotency key as "processed" for events
                # the agent's process_event() returns early on, which would
                # then cause the real trigger event to be skipped forever.
                event_type = event_data.get("eventType")
                if self.EVENT_TYPES and event_type not in self.EVENT_TYPES:
                    await self.redis.xack(self.stream_name, self.consumer_group, message_id)
                    processed += 1
                    continue

                # Extract application ID for idempotency
                payload = event_data.get("data") or {}
                application_id = payload.get("applicationId") or event_data.get("applicationId")
                
                # Derive idempotency key if repository is available
                idempotency_key = None
                if application_id and self._repository and self.STAGE_NAME:
                    application = self._repository.get(application_id)
                    if application:
                        attempt = application.stageAttempts.get(self.STAGE_NAME, 0) + 1
                        idempotency_key = self._derive_idempotency_key(application_id, attempt)
                        
                        # Check if already processed
                        if await self._is_already_processed(idempotency_key):
                            logger.info(
                                "Event already processed, skipping",
                                application_id=application_id,
                                idempotency_key=idempotency_key,
                            )
                            await self.redis.xack(self.stream_name, self.consumer_group, message_id)
                            processed += 1
                            continue
                
                try:
                    await self.process_event(event_data, idempotency_key=idempotency_key)
                    
                    # Mark as processed if we have idempotency key
                    if idempotency_key:
                        await self._mark_processed(idempotency_key)
                    
                except Exception as exc:
                    logger.error("Failed to process event", error=str(exc), exc_info=True)
                    
                    # Persist failure if we have repository and application_id
                    if application_id and self._repository and self.STAGE_NAME:
                        application = self._repository.get(application_id)
                        if application:
                            attempt = application.stageAttempts.get(self.STAGE_NAME, 0) + 1
                            last_error = self._classify_error(exc, self.STAGE_NAME, attempt)
                            self._repository.record_stage_failure(
                                application_id=application_id,
                                stage=self.STAGE_NAME,
                                error=last_error,
                            )
                            logger.info(
                                "Recorded stage failure",
                                application_id=application_id,
                                stage=self.STAGE_NAME,
                                error_code=last_error.code,
                                retryable=last_error.retryable,
                            )
                    
                    # Always ACK — let resubmit drive retry
                    await self.redis.xack(self.stream_name, self.consumer_group, message_id)
                    processed += 1
                    continue

                await self.redis.xack(self.stream_name, self.consumer_group, message_id)
                processed += 1

        return processed

    async def run(self, stop_event: asyncio.Event | None = None) -> None:
        while True:
            if stop_event and stop_event.is_set():
                return
            try:
                await self.process_one()
            except asyncio.CancelledError:
                raise
            except (RedisTimeoutError, asyncio.TimeoutError):
                # Benign: the blocking XREADGROUP read timed out on an idle
                # stream. The next iteration re-issues the read immediately, so
                # no message is ever missed. Log at debug to avoid flooding.
                logger.debug(
                    "Idle read timeout; re-polling",
                    group=self.consumer_group,
                    consumer=self.consumer_name,
                )
            except Exception as exc:
                # A transient error (e.g. Redis connection reset on token
                # refresh) must never silently kill the consumer loop. Log it
                # and retry after a short backoff so the worker self-heals.
                logger.error(
                    "Consumer loop error; retrying",
                    group=self.consumer_group,
                    consumer=self.consumer_name,
                    error=str(exc),
                    exc_info=True,
                )
                await asyncio.sleep(self.retry_delay)

    async def get_lag(self) -> int | None:
        try:
            info = await self.redis.xpending(self.stream_name, self.consumer_group)
            if isinstance(info, dict):
                return info.get("pending", 0)
        except Exception as exc:
            logger.warning("Failed to read consumer lag", error=str(exc))
        return None

    def _decode_fields(self, fields) -> dict:
        decoded: dict = {}
        for key, value in fields.items():
            k = key.decode() if isinstance(key, (bytes, bytearray)) else key
            if isinstance(value, (bytes, bytearray)):
                try:
                    decoded_value = value.decode()
                except Exception:
                    decoded_value = value
            else:
                decoded_value = value
            decoded[k] = decoded_value

        if "data" in decoded:
            try:
                decoded["data"] = json.loads(decoded["data"]) if isinstance(decoded["data"], str) else decoded["data"]
            except json.JSONDecodeError:
                pass
        return decoded
