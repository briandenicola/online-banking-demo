from __future__ import annotations

import abc
import asyncio
import json

import structlog

logger = structlog.get_logger("account-opening-consumer")


class AgentConsumer(abc.ABC):
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
    async def process_event(self, event_data: dict) -> None:
        ...

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
                try:
                    await self.process_event(event_data)
                except Exception as exc:
                    logger.error("Failed to process event", error=str(exc))
                    if self.retry_delay:
                        await asyncio.sleep(self.retry_delay)
                    continue

                await self.redis.xack(self.stream_name, self.consumer_group, message_id)
                processed += 1

        return processed

    async def run(self, stop_event: asyncio.Event | None = None) -> None:
        while True:
            if stop_event and stop_event.is_set():
                return
            await self.process_one()

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
