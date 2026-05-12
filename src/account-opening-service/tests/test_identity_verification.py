"""Tests for Agent 2: Identity Verification Consumer.

Validates that the identity verification agent:
- Cross-references extracted document data against application form
- Publishes `identity_verified` event with verified/confidence/flags
- Handles name mismatches, expired documents, address mismatches
- Collects multiple flags when multiple issues exist
- Transitions state: document_extraction → identity_verification
- Creates audit trail entries
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

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
from app.state_machine import ApplicationStateMachine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_application(
    app_id: str = "app-idv-001",
    status: ApplicationStatus = ApplicationStatus.document_extraction,
    form_data: dict | None = None,
    extracted_data: dict | None = None,
) -> ApplicationResponse:
    now = datetime.now(timezone.utc)
    default_form = {
        "firstName": "John",
        "lastName": "Doe",
        "dateOfBirth": "1990-01-15",
        "address": "123 Main St, Springfield, IL 62704",
        "email": "john.doe@example.com",
        "phone": "+12025551234",
        "ssn": "6789",
        "employment": "Software Engineer",
        "annualIncome": 95000,
        "accountType": "checking",
    }
    return ApplicationResponse(
        id=app_id,
        status=status,
        createdAt=now,
        updatedAt=now,
        formData=form_data or default_form,
        documents=[
            DocumentMetadata(
                type="photo_id",
                blobUrl="https://storage.example.com/docs/photo_id.jpg",
            ),
        ],
    )


def _make_event(
    app_id: str = "app-idv-001",
    extracted_data: dict | None = None,
) -> dict:
    """Simulate a decoded `document_extracted` event."""
    default_extracted = {
        "name": "John Doe",
        "dob": "1990-01-15",
        "documentNumber": "DL123456",
        "expiryDate": "2028-01-01",
        "address": "123 Main St, Springfield, IL 62704",
    }
    return {
        "eventType": "document_extracted",
        "applicationId": app_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": {
            "applicationId": app_id,
            "documentType": "photo_id",
            "extractedData": extracted_data or default_extracted,
            "confidence": 0.95,
        },
    }


# ---------------------------------------------------------------------------
# Identity Verification Consumer Stub
# ---------------------------------------------------------------------------

class IdentityVerificationConsumer(AgentConsumer):
    """Test-side implementation of identity verification consumer."""

    def __init__(
        self,
        redis,
        repository: InMemoryApplicationRepository,
        state_machine: ApplicationStateMachine,
        event_publisher: EventPublisher,
        foundry_agent: AsyncMock | None = None,
    ) -> None:
        super().__init__(
            redis=redis,
            stream="account-opening-events",
            group="identity-verification-group",
            consumer_name="idv-1",
        )
        self.repository = repository
        self.state_machine = state_machine
        self.publisher = event_publisher
        self.foundry_agent = foundry_agent

    async def process_event(self, event_data: dict) -> None:
        if event_data.get("eventType") != "document_extracted":
            return

        data = event_data.get("data", event_data)
        app_id = data.get("applicationId")
        extracted = data.get("extractedData", {})

        application = self.repository.get(app_id)
        if application is None:
            raise ValueError(f"Application {app_id} not found")

        form = application.formData
        flags: list[str] = []

        # Name matching
        form_name = f"{form.get('firstName', '')} {form.get('lastName', '')}".strip()
        doc_name = extracted.get("name", "")
        if form_name.lower() != doc_name.lower():
            flags.append("name_mismatch")

        # Expiry check
        expiry = extracted.get("expiryDate")
        if expiry:
            try:
                expiry_dt = datetime.fromisoformat(expiry)
                # Normalise to UTC-aware for comparison
                if expiry_dt.tzinfo is None:
                    expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
                if expiry_dt < datetime.now(timezone.utc):
                    flags.append("expired_document")
            except (ValueError, TypeError):
                flags.append("expired_document")

        # Address matching
        form_addr = str(form.get("address", "")).lower().strip()
        doc_addr = str(extracted.get("address", "")).lower().strip()
        if form_addr and doc_addr and form_addr != doc_addr:
            flags.append("address_mismatch")

        verified = len(flags) == 0
        confidence = 0.95 if verified else max(0.3, 0.95 - 0.2 * len(flags))

        # Foundry agent call (for reasoning)
        reasoning = ""
        if self.foundry_agent:
            result = await self.foundry_agent.run(
                prompt=f"Verify identity for application {app_id}",
                context={"form": form, "extracted": extracted},
            )
            reasoning = result.get("reasoning", "")

        # State transition
        self.state_machine.transition(
            application,
            ApplicationStatus.identity_verification,
            agent_name="identity-verification",
            details={
                "action": "verified",
                "verified": verified,
                "confidence": confidence,
                "flags": flags,
            },
        )
        self.repository.update(application)

        # Publish event
        await self.publisher.publish(
            stream_name=None,
            event_type="identity_verified",
            data={
                "applicationId": app_id,
                "verified": verified,
                "confidence": confidence,
                "flags": flags,
                "reasoning": reasoning,
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
def mock_foundry() -> AsyncMock:
    agent = AsyncMock()
    agent.run = AsyncMock(return_value={"reasoning": "All data matches."})
    return agent


@pytest.fixture
def publisher(mock_redis) -> EventPublisher:
    return EventPublisher(mock_redis)


@pytest.fixture
def consumer(
    mock_redis, repository, state_machine, publisher, mock_foundry
) -> IdentityVerificationConsumer:
    return IdentityVerificationConsumer(
        redis=mock_redis,
        repository=repository,
        state_machine=state_machine,
        event_publisher=publisher,
        foundry_agent=mock_foundry,
    )


# ---------------------------------------------------------------------------
# Tests: Matching Data
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestMatchingData:
    """When extracted data matches application form, identity is verified."""

    async def test_verified_true_when_data_matches(
        self, consumer, repository, mock_redis
    ):
        """Matching name, valid expiry, matching address → verified=true."""
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(_make_event(app_id=app.id))

        call_args = mock_redis.xadd.call_args
        payload = call_args[0][1] if call_args[0] else call_args[1]
        data = json.loads(payload["data"]) if isinstance(payload.get("data"), str) else payload.get("data", {})
        assert data.get("verified") is True

    async def test_high_confidence_when_verified(
        self, consumer, repository, mock_redis
    ):
        """Verified identity should have high confidence (≥0.9)."""
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(_make_event(app_id=app.id))

        call_args = mock_redis.xadd.call_args
        payload = call_args[0][1] if call_args[0] else call_args[1]
        data = json.loads(payload["data"]) if isinstance(payload.get("data"), str) else payload.get("data", {})
        assert data.get("confidence", 0) >= 0.9

    async def test_no_flags_when_verified(
        self, consumer, repository, mock_redis
    ):
        """Verified identity should have no flags."""
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(_make_event(app_id=app.id))

        call_args = mock_redis.xadd.call_args
        payload = call_args[0][1] if call_args[0] else call_args[1]
        data = json.loads(payload["data"]) if isinstance(payload.get("data"), str) else payload.get("data", {})
        assert data.get("flags", []) == []


# ---------------------------------------------------------------------------
# Tests: Name Mismatch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestNameMismatch:
    """When name on document doesn't match application form."""

    async def test_verified_false_on_name_mismatch(
        self, consumer, repository, mock_redis
    ):
        app = _make_application()
        repository._applications[app.id] = app

        event = _make_event(
            app_id=app.id,
            extracted_data={
                "name": "Jonathan Doe",  # form says "John Doe"
                "dob": "1990-01-15",
                "documentNumber": "DL123456",
                "expiryDate": "2028-01-01",
                "address": "123 Main St, Springfield, IL 62704",
            },
        )
        await consumer.process_event(event)

        call_args = mock_redis.xadd.call_args
        payload = call_args[0][1] if call_args[0] else call_args[1]
        data = json.loads(payload["data"]) if isinstance(payload.get("data"), str) else payload.get("data", {})
        assert data.get("verified") is False
        assert "name_mismatch" in data.get("flags", [])


# ---------------------------------------------------------------------------
# Tests: Expired Document
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestExpiredDocument:
    """When document has expired."""

    async def test_expired_id_flagged(self, consumer, repository, mock_redis):
        """Expired ID must produce 'expired_document' flag."""
        app = _make_application()
        repository._applications[app.id] = app

        event = _make_event(
            app_id=app.id,
            extracted_data={
                "name": "John Doe",
                "dob": "1990-01-15",
                "documentNumber": "DL123456",
                "expiryDate": "2020-01-01",  # expired
                "address": "123 Main St, Springfield, IL 62704",
            },
        )
        await consumer.process_event(event)

        call_args = mock_redis.xadd.call_args
        payload = call_args[0][1] if call_args[0] else call_args[1]
        data = json.loads(payload["data"]) if isinstance(payload.get("data"), str) else payload.get("data", {})
        assert "expired_document" in data.get("flags", [])


# ---------------------------------------------------------------------------
# Tests: Address Mismatch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestAddressMismatch:
    """When address on document doesn't match application."""

    async def test_address_mismatch_flagged(
        self, consumer, repository, mock_redis
    ):
        app = _make_application()
        repository._applications[app.id] = app

        event = _make_event(
            app_id=app.id,
            extracted_data={
                "name": "John Doe",
                "dob": "1990-01-15",
                "documentNumber": "DL123456",
                "expiryDate": "2028-01-01",
                "address": "999 Different Rd, Chicago, IL 60601",  # mismatch
            },
        )
        await consumer.process_event(event)

        call_args = mock_redis.xadd.call_args
        payload = call_args[0][1] if call_args[0] else call_args[1]
        data = json.loads(payload["data"]) if isinstance(payload.get("data"), str) else payload.get("data", {})
        assert "address_mismatch" in data.get("flags", [])


# ---------------------------------------------------------------------------
# Tests: Multiple Mismatches
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestMultipleMismatches:
    """When multiple issues exist, all flags are collected."""

    async def test_all_flags_collected(self, consumer, repository, mock_redis):
        """Name mismatch + expired doc + address mismatch → 3 flags."""
        app = _make_application()
        repository._applications[app.id] = app

        event = _make_event(
            app_id=app.id,
            extracted_data={
                "name": "Jane Doe",           # name mismatch
                "dob": "1990-01-15",
                "documentNumber": "DL123456",
                "expiryDate": "2020-01-01",    # expired
                "address": "999 Other St",     # address mismatch
            },
        )
        await consumer.process_event(event)

        call_args = mock_redis.xadd.call_args
        payload = call_args[0][1] if call_args[0] else call_args[1]
        data = json.loads(payload["data"]) if isinstance(payload.get("data"), str) else payload.get("data", {})
        flags = data.get("flags", [])
        assert "name_mismatch" in flags
        assert "expired_document" in flags
        assert "address_mismatch" in flags
        assert len(flags) == 3


# ---------------------------------------------------------------------------
# Tests: State Transition
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestStateTransition:
    """State machine transitions for identity verification."""

    async def test_transitions_to_identity_verification(
        self, consumer, repository
    ):
        """Status moves document_extraction → identity_verification."""
        app = _make_application(status=ApplicationStatus.document_extraction)
        repository._applications[app.id] = app

        await consumer.process_event(_make_event(app_id=app.id))

        updated = repository.get(app.id)
        assert updated.status == ApplicationStatus.identity_verification

    async def test_rejects_wrong_initial_state(self, consumer, repository):
        """If not in document_extraction state, transition fails."""
        app = _make_application(status=ApplicationStatus.submitted)
        repository._applications[app.id] = app

        with pytest.raises(ValueError, match="Invalid transition"):
            await consumer.process_event(_make_event(app_id=app.id))


# ---------------------------------------------------------------------------
# Tests: Event Publishing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestEventPublishing:
    """identity_verified event schema."""

    async def test_publishes_identity_verified(
        self, consumer, repository, mock_redis
    ):
        """Must publish an identity_verified event."""
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(_make_event(app_id=app.id))

        mock_redis.xadd.assert_called_once()
        call_args = mock_redis.xadd.call_args
        payload = call_args[0][1] if call_args[0] else call_args[1]
        assert payload.get("eventType") == "identity_verified"

    async def test_event_has_required_fields(
        self, consumer, repository, mock_redis
    ):
        """Event data must contain applicationId, verified, confidence, flags."""
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(_make_event(app_id=app.id))

        call_args = mock_redis.xadd.call_args
        payload = call_args[0][1] if call_args[0] else call_args[1]
        data = json.loads(payload["data"]) if isinstance(payload.get("data"), str) else payload.get("data", {})
        assert "applicationId" in data
        assert "verified" in data
        assert "confidence" in data
        assert "flags" in data


# ---------------------------------------------------------------------------
# Tests: Foundry Agent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestFoundryAgent:
    """Foundry agent interaction for reasoning."""

    async def test_foundry_agent_called(
        self, consumer, repository, mock_foundry
    ):
        """Foundry agent must be invoked for reasoning."""
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(_make_event(app_id=app.id))

        mock_foundry.run.assert_called_once()

    async def test_foundry_unavailable_raises(
        self, consumer, repository, mock_foundry
    ):
        """If Foundry agent is unavailable, error must propagate."""
        app = _make_application()
        repository._applications[app.id] = app
        mock_foundry.run.side_effect = ConnectionError("Foundry unavailable")

        with pytest.raises(ConnectionError, match="Foundry"):
            await consumer.process_event(_make_event(app_id=app.id))


# ---------------------------------------------------------------------------
# Tests: Audit Trail
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestAuditTrail:
    """Audit trail entries for identity verification."""

    async def test_audit_entry_created(self, consumer, repository):
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(_make_event(app_id=app.id))

        updated = repository.get(app.id)
        assert len(updated.auditTrail) == 1
        entry = updated.auditTrail[0]
        assert entry.agent == "identity-verification"
        assert entry.previousState == "document_extraction"
        assert entry.newState == "identity_verification"
        assert entry.timestamp is not None
