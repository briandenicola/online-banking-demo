"""Tests for the Redis Streams consumer base class (AgentConsumer).

Validates the consumer framework that all 4 agents will use:
- Consumer group creation (XGROUP CREATE)
- Event processing delegates to subclass process_event()
- ACK after successful processing
- Error handling when process_event fails
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
class TestConsumerGroupCreation:
    """Verify consumer group setup via XGROUP CREATE."""

    async def test_creates_consumer_group_on_start(self, mock_redis):
        """AgentConsumer must create its consumer group on initialization."""
        from app.consumer import AgentConsumer

        class TestConsumer(AgentConsumer):
            async def process_event(self, event_data: dict, idempotency_key=None) -> None:
                pass

        consumer = TestConsumer(
            redis=mock_redis,
            stream="account-opening-events",
            group="test-group",
            consumer_name="test-consumer-1",
        )
        await consumer.setup()

        mock_redis.xgroup_create.assert_called_once()
        call_args = mock_redis.xgroup_create.call_args
        # Verify stream and group name
        args_str = str(call_args)
        assert "account-opening-events" in args_str
        assert "test-group" in args_str

    async def test_handles_group_already_exists(self, mock_redis):
        """If the consumer group already exists, setup should not crash."""
        from app.consumer import AgentConsumer

        class TestConsumer(AgentConsumer):
            async def process_event(self, event_data: dict, idempotency_key=None) -> None:
                pass

        # Simulate "BUSYGROUP Consumer Group name already exists"
        mock_redis.xgroup_create.side_effect = Exception(
            "BUSYGROUP Consumer Group name already exists"
        )

        consumer = TestConsumer(
            redis=mock_redis,
            stream="account-opening-events",
            group="existing-group",
            consumer_name="test-consumer-1",
        )

        # Should not raise
        await consumer.setup()


@pytest.mark.asyncio
class TestEventProcessing:
    """Verify that events are dispatched to process_event()."""

    async def test_process_event_called_on_message(self, mock_redis):
        """When a message is read, process_event must be called with the data."""
        from app.consumer import AgentConsumer

        processed_events = []

        class TestConsumer(AgentConsumer):
            async def process_event(self, event_data: dict, idempotency_key=None) -> None:
                processed_events.append(event_data)

        # Simulate xreadgroup returning one message
        mock_redis.xreadgroup.return_value = [
            (
                b"account-opening-events",
                [(b"1234-0", {b"data": b'{"applicationId": "app-100"}', b"eventType": b"document_uploaded"})],
            )
        ]
        # Stop after one iteration
        mock_redis.xreadgroup.side_effect = [
            mock_redis.xreadgroup.return_value,
            [],
        ]

        consumer = TestConsumer(
            redis=mock_redis,
            stream="account-opening-events",
            group="test-group",
            consumer_name="test-consumer-1",
        )
        await consumer.setup()
        await consumer.process_one()

        assert len(processed_events) == 1


@pytest.mark.asyncio
class TestAcknowledgement:
    """Verify messages are ACKed after successful processing."""

    async def test_ack_after_successful_processing(self, mock_redis):
        """After process_event succeeds, the message must be ACKed."""
        from app.consumer import AgentConsumer

        class TestConsumer(AgentConsumer):
            async def process_event(self, event_data: dict, idempotency_key=None) -> None:
                pass  # Success

        mock_redis.xreadgroup.return_value = [
            (
                b"account-opening-events",
                [(b"1234-0", {b"data": b'{"applicationId": "app-200"}', b"eventType": b"document_uploaded"})],
            )
        ]

        consumer = TestConsumer(
            redis=mock_redis,
            stream="account-opening-events",
            group="test-group",
            consumer_name="test-consumer-1",
        )
        await consumer.setup()
        await consumer.process_one()

        mock_redis.xack.assert_called_once()


@pytest.mark.asyncio
class TestEventTypeFiltering:
    """Regression: events outside EVENT_TYPES must not poison idempotency keys.

    Bug: when an agent's process_event() returned early on a non-matching
    eventType, the base consumer still derived and marked the per-stage
    idempotency key as 'processed'. The next (correct) event for that stage
    then matched the same key and was silently skipped, leaving applications
    stuck at 'submitted' with empty agentResults.
    """

    async def test_unrelated_event_is_acked_without_processing(self, mock_redis):
        from app.consumer import AgentConsumer

        process_calls: list[dict] = []

        class FilteredConsumer(AgentConsumer):
            STAGE_NAME = "document_extraction"
            EVENT_TYPES = frozenset({"document_uploaded"})

            async def process_event(self, event_data: dict, idempotency_key=None) -> None:
                process_calls.append(event_data)

        mock_redis.xreadgroup.return_value = [
            (
                b"account-opening-events",
                [(b"1-0", {b"data": b'{"applicationId": "app-1"}', b"eventType": b"application_submitted"})],
            )
        ]

        consumer = FilteredConsumer(
            redis=mock_redis,
            stream="account-opening-events",
            group="document-extraction-group",
            consumer_name="c1",
        )
        await consumer.setup()
        await consumer.process_one()

        # Event must be acked so it doesn't redeliver forever...
        mock_redis.xack.assert_called_once()
        # ...but process_event must NOT run...
        assert process_calls == []
        # ...and idempotency must NOT be touched (no sadd/sismember).
        mock_redis.sadd.assert_not_called()
        mock_redis.sismember.assert_not_called()

    async def test_matching_event_still_processes(self, mock_redis):
        from app.consumer import AgentConsumer

        process_calls: list[dict] = []

        class FilteredConsumer(AgentConsumer):
            STAGE_NAME = "document_extraction"
            EVENT_TYPES = frozenset({"document_uploaded"})

            async def process_event(self, event_data: dict, idempotency_key=None) -> None:
                process_calls.append(event_data)

        mock_redis.xreadgroup.return_value = [
            (
                b"account-opening-events",
                [(b"2-0", {b"data": b'{"applicationId": "app-2"}', b"eventType": b"document_uploaded"})],
            )
        ]

        consumer = FilteredConsumer(
            redis=mock_redis,
            stream="account-opening-events",
            group="document-extraction-group",
            consumer_name="c1",
        )
        await consumer.setup()
        await consumer.process_one()

        assert len(process_calls) == 1
        mock_redis.xack.assert_called_once()


@pytest.mark.asyncio
class TestErrorHandling:
    """Verify resilience when process_event fails."""

    async def test_does_not_crash_on_process_event_failure(self, mock_redis):
        """If process_event raises, the consumer must not crash."""
        from app.consumer import AgentConsumer

        class FailingConsumer(AgentConsumer):
            async def process_event(self, event_data: dict, idempotency_key=None) -> None:
                raise RuntimeError("Agent processing failed")

        mock_redis.xreadgroup.return_value = [
            (
                b"account-opening-events",
                [(b"5678-0", {b"data": b'{"applicationId": "app-300"}', b"eventType": b"test_event"})],
            )
        ]

        consumer = FailingConsumer(
            redis=mock_redis,
            stream="account-opening-events",
            group="test-group",
            consumer_name="test-consumer-1",
        )
        await consumer.setup()

        # Should not raise — error must be caught internally
        await consumer.process_one()

    async def test_no_ack_on_process_event_failure(self, mock_redis):
        """On failure the consumer ACKs anyway so the resubmit endpoint drives
        retry — see consumer.py:194 ('Always ACK — let resubmit drive retry').
        Originally this asserted no-ack, but the resubmit-driven retry model
        was adopted in #135/#136. This test now pins the current behavior so
        future changes can't silently regress it.
        """
        from app.consumer import AgentConsumer

        class FailingConsumer(AgentConsumer):
            async def process_event(self, event_data: dict, idempotency_key=None) -> None:
                raise RuntimeError("Agent processing failed")

        mock_redis.xreadgroup.return_value = [
            (
                b"account-opening-events",
                [(b"9999-0", {b"data": b'{"applicationId": "app-400"}', b"eventType": b"test_event"})],
            )
        ]

        consumer = FailingConsumer(
            redis=mock_redis,
            stream="account-opening-events",
            group="test-group",
            consumer_name="test-consumer-1",
        )
        await consumer.setup()
        await consumer.process_one()

        # Message IS acked even on failure; retry is driven by the
        # resubmit endpoint, not stream redelivery.
        mock_redis.xack.assert_called_once()
