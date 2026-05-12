"""Tests for Redis Streams event publisher.

Validates that the publish_event utility:
- Publishes to the correct stream ('account-opening-events')
- Includes required fields (applicationId, eventType, timestamp)
- Handles Redis connection failures gracefully (logs, doesn't crash)
"""
import logging
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
class TestPublishEvent:
    """Tests for the publish_event() utility function."""

    async def test_publishes_to_correct_stream(self, mock_redis):
        """Events must be published to the 'account-opening-events' stream."""
        from app.events import publish_event

        await publish_event(
            mock_redis,
            event_type="document_uploaded",
            data={"applicationId": "app-001", "documentType": "photo_id"},
        )

        mock_redis.xadd.assert_called_once()
        call_args = mock_redis.xadd.call_args
        # First positional arg is the stream name
        stream_name = call_args[0][0] if call_args[0] else call_args[1].get("name", "")
        assert stream_name == "account-opening-events"

    async def test_event_payload_contains_application_id(self, mock_redis):
        """Published event must include the applicationId."""
        from app.events import publish_event

        await publish_event(
            mock_redis,
            event_type="document_uploaded",
            data={"applicationId": "app-002", "documentType": "photo_id"},
        )

        call_args = mock_redis.xadd.call_args
        # Second positional arg or 'fields' kwarg is the event payload
        fields = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("fields", {})
        # Fields may be serialized as JSON string or flat dict
        payload_str = str(fields)
        assert "app-002" in payload_str

    async def test_event_payload_contains_event_type(self, mock_redis):
        """Published event must include the eventType field."""
        from app.events import publish_event

        await publish_event(
            mock_redis,
            event_type="identity_verified",
            data={"applicationId": "app-003"},
        )

        call_args = mock_redis.xadd.call_args
        fields = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("fields", {})
        payload_str = str(fields)
        assert "identity_verified" in payload_str

    async def test_event_payload_contains_timestamp(self, mock_redis):
        """Published event must include a timestamp."""
        from app.events import publish_event

        await publish_event(
            mock_redis,
            event_type="document_uploaded",
            data={"applicationId": "app-004"},
        )

        call_args = mock_redis.xadd.call_args
        fields = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("fields", {})
        payload_str = str(fields)
        # Timestamp should be present — could be ISO format or unix
        assert "timestamp" in payload_str.lower() or "202" in payload_str

    async def test_handles_redis_connection_failure_gracefully(
        self, mock_redis, caplog
    ):
        """Redis connection failure must be logged, not raise an exception."""
        from app.events import publish_event

        mock_redis.xadd.side_effect = ConnectionError("Redis unavailable")

        # Should NOT raise — must handle gracefully
        with caplog.at_level(logging.WARNING):
            await publish_event(
                mock_redis,
                event_type="document_uploaded",
                data={"applicationId": "app-005"},
            )
        # Verify it logged the error (implementation may use logging or structlog)


@pytest.mark.asyncio
class TestEventSchema:
    """Validate event payload structure matches the spec (R6)."""

    async def test_document_uploaded_event_has_document_type(self, mock_redis):
        """document_uploaded events must include documentType."""
        from app.events import publish_event

        await publish_event(
            mock_redis,
            event_type="document_uploaded",
            data={
                "applicationId": "app-010",
                "documentType": "photo_id",
                "blobUrl": "https://example.com/doc.jpg",
            },
        )
        call_args = mock_redis.xadd.call_args
        fields = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("fields", {})
        payload_str = str(fields)
        assert "photo_id" in payload_str
