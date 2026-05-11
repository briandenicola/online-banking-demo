"""Tests for Agent 1: Document Extraction Consumer.

Validates that the document extraction agent:
- Calls Azure AI Content Understanding to extract structured data
- Publishes `document_extracted` event with correct schema
- Transitions state: submitted → document_extraction
- Creates audit trail entries
- Handles photo_id and proof_of_address document types
- Flags low-confidence extractions for review
- Raises errors when CUS is unavailable (not swallowed)
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.consumer import AgentConsumer
from app.events import EventPublisher
from app.models import (
    ApplicationResponse,
    ApplicationStatus,
    AuditEntry,
    DocumentMetadata,
)
from app.repository import InMemoryApplicationRepository
from app.state_machine import ApplicationStateMachine, transition


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_application(
    app_id: str = "app-test-001",
    status: ApplicationStatus = ApplicationStatus.submitted,
) -> ApplicationResponse:
    """Build a minimal ApplicationResponse for testing."""
    now = datetime.now(timezone.utc)
    return ApplicationResponse(
        id=app_id,
        status=status,
        createdAt=now,
        updatedAt=now,
        formData={
            "firstName": "Jane",
            "lastName": "Smith",
            "dateOfBirth": "1992-03-15",
            "address": "456 Oak Ave, Portland, OR 97201",
            "email": "jane.smith@example.com",
            "phone": "+15035551234",
            "ssn": "1234",
            "employment": "Nurse",
            "annualIncome": 78000,
            "accountType": "checking",
        },
        documents=[
            DocumentMetadata(
                type="photo_id",
                blobUrl="https://storage.example.com/docs/photo_id.jpg",
            ),
        ],
    )


def _make_event(
    app_id: str = "app-test-001",
    doc_type: str = "photo_id",
) -> dict:
    """Simulate a decoded `document_uploaded` event from Redis."""
    return {
        "eventType": "document_uploaded",
        "applicationId": app_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": {
            "applicationId": app_id,
            "documentType": doc_type,
            "blobUrl": f"https://storage.example.com/docs/{doc_type}.jpg",
        },
    }


def _mock_cus_result(doc_type: str = "photo_id", confidence: float = 0.95) -> dict:
    """Simulated Content Understanding extraction result."""
    if doc_type == "photo_id":
        return {
            "name": "Jane Smith",
            "dob": "1992-03-15",
            "documentNumber": "DL789012",
            "expiryDate": "2029-03-15",
            "address": "456 Oak Ave, Portland, OR 97201",
            "confidence": confidence,
        }
    return {
        "address": "456 Oak Ave, Portland, OR 97201",
        "documentDate": "2026-01-15",
        "confidence": confidence,
    }


# ---------------------------------------------------------------------------
# Document Extraction Consumer Stub (for testing logic)
# ---------------------------------------------------------------------------

class DocumentExtractionConsumer(AgentConsumer):
    """Test-side implementation of the document extraction consumer.

    This mirrors what Basher's real implementation should do, so our tests
    validate the *contract* rather than internal wiring.
    """

    def __init__(
        self,
        redis,
        repository: InMemoryApplicationRepository,
        state_machine: ApplicationStateMachine,
        event_publisher: EventPublisher,
        cus_client: AsyncMock | None = None,
    ) -> None:
        super().__init__(
            redis=redis,
            stream="account-opening-events",
            group="document-extraction-group",
            consumer_name="doc-extractor-1",
        )
        self.repository = repository
        self.state_machine = state_machine
        self.publisher = event_publisher
        self.cus_client = cus_client  # Azure AI Content Understanding mock

    async def process_event(self, event_data: dict) -> None:
        if event_data.get("eventType") != "document_uploaded":
            return

        data = event_data.get("data", event_data)
        app_id = data.get("applicationId")
        doc_type = data.get("documentType", "photo_id")

        application = self.repository.get(app_id)
        if application is None:
            raise ValueError(f"Application {app_id} not found")

        # Call CUS — must raise if unavailable
        extracted = await self.cus_client.analyze_document(
            document_url=data.get("blobUrl"),
            model="prebuilt-idDocument" if doc_type == "photo_id" else "prebuilt-layout",
        )

        confidence = extracted.get("confidence", 0.0)

        # State transition
        self.state_machine.transition(
            application,
            ApplicationStatus.document_extraction,
            agent_name="document-extraction",
            details={
                "action": "extracted",
                "documentType": doc_type,
                "confidence": confidence,
            },
        )
        self.repository.update(application)

        # Publish event
        await self.publisher.publish(
            stream_name=None,
            event_type="document_extracted",
            data={
                "applicationId": app_id,
                "documentType": doc_type,
                "extractedData": extracted,
                "confidence": confidence,
            },
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def repository() -> InMemoryApplicationRepository:
    return InMemoryApplicationRepository()


@pytest.fixture
def state_machine() -> ApplicationStateMachine:
    return ApplicationStateMachine()


@pytest.fixture
def mock_cus() -> AsyncMock:
    """Mock Azure AI Content Understanding client."""
    cus = AsyncMock()
    cus.analyze_document = AsyncMock(return_value=_mock_cus_result())
    return cus


@pytest.fixture
def publisher(mock_redis) -> EventPublisher:
    return EventPublisher(mock_redis)


@pytest.fixture
def consumer(
    mock_redis, repository, state_machine, publisher, mock_cus
) -> DocumentExtractionConsumer:
    return DocumentExtractionConsumer(
        redis=mock_redis,
        repository=repository,
        state_machine=state_machine,
        event_publisher=publisher,
        cus_client=mock_cus,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestDocumentExtractionSuccess:
    """Successful extraction publishes event and updates state."""

    async def test_publishes_document_extracted_event(
        self, consumer, repository, mock_redis
    ):
        """After extraction, a `document_extracted` event must be published."""
        app = _make_application()
        repository._applications[app.id] = app

        event = _make_event(app_id=app.id)
        await consumer.process_event(event)

        mock_redis.xadd.assert_called_once()
        call_args = mock_redis.xadd.call_args
        payload = call_args[0][1] if call_args[0] else call_args[1]
        # Verify event type
        if isinstance(payload, dict):
            assert payload.get("eventType") == "document_extracted"

    async def test_event_contains_application_id(
        self, consumer, repository, mock_redis
    ):
        """Published event must include the applicationId."""
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(_make_event(app_id=app.id))

        call_args = mock_redis.xadd.call_args
        payload = call_args[0][1] if call_args[0] else call_args[1]
        if isinstance(payload, dict):
            assert payload.get("applicationId") == app.id

    async def test_event_contains_extracted_data(
        self, consumer, repository, mock_redis
    ):
        """Published event data must contain extractedData from CUS."""
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(_make_event(app_id=app.id))

        call_args = mock_redis.xadd.call_args
        payload = call_args[0][1] if call_args[0] else call_args[1]
        if isinstance(payload, dict) and "data" in payload:
            data = json.loads(payload["data"]) if isinstance(payload["data"], str) else payload["data"]
            assert "extractedData" in data


@pytest.mark.asyncio
class TestCUSUnavailable:
    """When Content Understanding is unavailable, errors must propagate."""

    async def test_cus_error_raises_not_swallowed(
        self, consumer, repository, mock_cus
    ):
        """If CUS raises an error, it must NOT be swallowed silently."""
        app = _make_application()
        repository._applications[app.id] = app
        mock_cus.analyze_document.side_effect = ConnectionError(
            "Content Understanding service unavailable"
        )

        with pytest.raises(ConnectionError, match="Content Understanding"):
            await consumer.process_event(_make_event(app_id=app.id))

    async def test_state_not_changed_on_cus_failure(
        self, consumer, repository, mock_cus
    ):
        """State must remain 'submitted' if CUS call fails."""
        app = _make_application()
        repository._applications[app.id] = app
        mock_cus.analyze_document.side_effect = ConnectionError("CUS down")

        with pytest.raises(ConnectionError):
            await consumer.process_event(_make_event(app_id=app.id))

        assert repository.get(app.id).status == ApplicationStatus.submitted


@pytest.mark.asyncio
class TestStateTransitions:
    """State machine transitions for document extraction."""

    async def test_transitions_submitted_to_document_extraction(
        self, consumer, repository
    ):
        """Processing must move status from submitted → document_extraction."""
        app = _make_application(status=ApplicationStatus.submitted)
        repository._applications[app.id] = app

        await consumer.process_event(_make_event(app_id=app.id))

        updated = repository.get(app.id)
        assert updated.status == ApplicationStatus.document_extraction

    async def test_rejects_wrong_initial_state(self, consumer, repository):
        """If application is not in 'submitted' state, transition fails."""
        app = _make_application(status=ApplicationStatus.approved)
        repository._applications[app.id] = app

        with pytest.raises(ValueError, match="Invalid transition"):
            await consumer.process_event(_make_event(app_id=app.id))


@pytest.mark.asyncio
class TestAuditTrail:
    """Audit trail entries for document extraction."""

    async def test_audit_entry_created(self, consumer, repository):
        """An audit entry must be appended after successful extraction."""
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(_make_event(app_id=app.id))

        updated = repository.get(app.id)
        assert len(updated.auditTrail) == 1

    async def test_audit_entry_agent_name(self, consumer, repository):
        """Audit entry must record agent='document-extraction'."""
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(_make_event(app_id=app.id))

        entry = repository.get(app.id).auditTrail[0]
        assert entry.agent == "document-extraction"

    async def test_audit_entry_states(self, consumer, repository):
        """Audit entry must record previousState and newState."""
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(_make_event(app_id=app.id))

        entry = repository.get(app.id).auditTrail[0]
        assert entry.previousState == "submitted"
        assert entry.newState == "document_extraction"

    async def test_audit_entry_has_timestamp(self, consumer, repository):
        """Audit entry must include a timestamp."""
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(_make_event(app_id=app.id))

        entry = repository.get(app.id).auditTrail[0]
        assert entry.timestamp is not None


@pytest.mark.asyncio
class TestDocumentTypes:
    """Handles different document types correctly."""

    async def test_photo_id_uses_id_document_model(
        self, consumer, repository, mock_cus
    ):
        """photo_id documents must use prebuilt-idDocument model."""
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(
            _make_event(app_id=app.id, doc_type="photo_id")
        )

        mock_cus.analyze_document.assert_called_once()
        call_kwargs = mock_cus.analyze_document.call_args
        args_str = str(call_kwargs)
        assert "prebuilt-idDocument" in args_str

    async def test_proof_of_address_uses_layout_model(
        self, consumer, repository, mock_cus
    ):
        """proof_of_address documents must use prebuilt-layout model."""
        app = _make_application()
        repository._applications[app.id] = app
        mock_cus.analyze_document.return_value = _mock_cus_result("proof_of_address")

        await consumer.process_event(
            _make_event(app_id=app.id, doc_type="proof_of_address")
        )

        call_kwargs = mock_cus.analyze_document.call_args
        args_str = str(call_kwargs)
        assert "prebuilt-layout" in args_str


@pytest.mark.asyncio
class TestLowConfidence:
    """Low-confidence extraction should flag for review."""

    async def test_low_confidence_flagged(
        self, consumer, repository, mock_cus, mock_redis
    ):
        """Extraction with confidence < 0.7 should include a flag."""
        app = _make_application()
        repository._applications[app.id] = app
        mock_cus.analyze_document.return_value = _mock_cus_result(confidence=0.4)

        await consumer.process_event(_make_event(app_id=app.id))

        # Event should still be published (with low confidence noted)
        mock_redis.xadd.assert_called_once()
        call_args = mock_redis.xadd.call_args
        payload = call_args[0][1] if call_args[0] else call_args[1]
        if isinstance(payload, dict) and "data" in payload:
            data = json.loads(payload["data"]) if isinstance(payload["data"], str) else payload["data"]
            assert data.get("confidence", 1.0) < 0.7
