from __future__ import annotations

import json
from datetime import datetime, timezone

import structlog

STREAM_NAME = "account-opening-events"
logger = structlog.get_logger("account-opening-events")


class EventPublisher:
    def __init__(self, redis_client, stream_name: str = STREAM_NAME) -> None:
        self._redis = redis_client
        self._stream = stream_name

    async def publish(self, stream_name: str | None, event_type: str, data: dict) -> None:
        await publish_event(
            self._redis,
            event_type=event_type,
            data=data,
            stream_name=stream_name or self._stream,
        )


async def publish_event(redis_client, event_type: str, data: dict, stream_name: str = STREAM_NAME) -> None:
    if not redis_client:
        logger.warning("Redis unavailable, skipping event publish", eventType=event_type)
        return

    payload = {
        "eventType": event_type,
        "applicationId": data.get("applicationId"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": json.dumps(data),
    }

    try:
        await redis_client.xadd(stream_name, payload)
    except Exception as exc:
        logger.warning("Failed to publish Redis event", error=str(exc), eventType=event_type)
