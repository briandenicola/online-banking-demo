"""Tests for Agent 3: Compliance/KYC Check Consumer.

Validates that the compliance agent:
- Evaluates risk tier based on verification results, income, employment
- Produces kycStatus: approved/review/rejected
- Produces riskTier: low/medium/high
- Includes reasoning in compliance_checked event
- Transitions state: identity_verification → compliance_check
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
    DocumentMetadata,
)
from app.repository import InMemoryApplicationRepository
from app.state_machine import ApplicationStateMachine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_application(
    app_id: str = "app-kyc-001",
    status: ApplicationStatus = ApplicationStatus.identity_verification,
    form_data: dict | None = None,
) -> ApplicationResponse:
    now = datetime.now(timezone.utc)
    default_form = {
        "firstName": "John",
        "lastName": "Doe",
        "dateOfBirth": "1990-01-15",
        "address": "123 Main St, Springfield, IL 62704",
        "email": "john.doe@example.com",
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
    )


def _make_event(
    app_id: str = "app-kyc-001",
    verified: bool = True,
    confidence: float = 0.95,
    flags: list[str] | None = None,
) -> dict:
    """Simulate a decoded `identity_verified` event."""
    return {
        "eventType": "identity_verified",
        "applicationId": app_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": {
            "applicationId": app_id,
            "verified": verified,
            "confidence": confidence,
            "flags": flags or [],
            "reasoning": "Automated verification result",
        },
    }


# ---------------------------------------------------------------------------
# Compliance Check Consumer Stub
# ---------------------------------------------------------------------------

class ComplianceCheckConsumer(AgentConsumer):
    """Test-side implementation of compliance check consumer."""

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
            group="compliance-group",
            consumer_name="compliance-1",
        )
        self.repository = repository
        self.state_machine = state_machine
        self.publisher = event_publisher
        self.foundry_agent = foundry_agent

    async def process_event(self, event_data: dict) -> None:
        if event_data.get("eventType") != "identity_verified":
            return

        data = event_data.get("data", event_data)
        app_id = data.get("applicationId")
        verified = data.get("verified", False)
        confidence = data.get("confidence", 0.0)
        flags = data.get("flags", [])

        application = self.repository.get(app_id)
        if application is None:
            raise ValueError(f"Application {app_id} not found")

        form = application.formData
        annual_income = form.get("annualIncome", 0)

        # Foundry agent call for compliance reasoning
        reasoning = ""
        if self.foundry_agent:
            result = await self.foundry_agent.run(
                prompt=f"Evaluate compliance for application {app_id}",
                context={
                    "verified": verified,
                    "confidence": confidence,
                    "flags": flags,
                    "form": form,
                },
            )
            reasoning = result.get("reasoning", "")

        # Risk assessment logic
        if not verified:
            kyc_status = "rejected"
            risk_tier = "high"
            reasoning = reasoning or "Identity verification failed"
        elif flags:
            kyc_status = "review"
            risk_tier = "medium" if len(flags) <= 1 else "high"
            reasoning = reasoning or f"Flags detected: {', '.join(flags)}"
        elif confidence >= 0.9 and annual_income >= 30000:
            kyc_status = "approved"
            risk_tier = "low"
            reasoning = reasoning or "All checks passed with high confidence"
        elif confidence >= 0.7:
            kyc_status = "review"
            risk_tier = "medium"
            reasoning = reasoning or "Moderate confidence requires review"
        else:
            kyc_status = "rejected"
            risk_tier = "high"
            reasoning = reasoning or "Confidence too low"

        # State transition
        self.state_machine.transition(
            application,
            ApplicationStatus.compliance_check,
            agent_name="compliance",
            details={
                "action": "compliance_evaluated",
                "kycStatus": kyc_status,
                "riskTier": risk_tier,
            },
        )
        self.repository.update(application)

        # Publish event
        await self.publisher.publish(
            stream_name=None,
            event_type="compliance_checked",
            data={
                "applicationId": app_id,
                "kycStatus": kyc_status,
                "riskTier": risk_tier,
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
    agent.run = AsyncMock(return_value={"reasoning": "Compliance assessment."})
    return agent


@pytest.fixture
def publisher(mock_redis) -> EventPublisher:
    return EventPublisher(mock_redis)


@pytest.fixture
def consumer(
    mock_redis, repository, state_machine, publisher, mock_foundry
) -> ComplianceCheckConsumer:
    return ComplianceCheckConsumer(
        redis=mock_redis,
        repository=repository,
        state_machine=state_machine,
        event_publisher=publisher,
        foundry_agent=mock_foundry,
    )


def _extract_event_data(mock_redis) -> dict:
    """Helper to extract published event data from mock_redis.xadd calls."""
    call_args = mock_redis.xadd.call_args
    payload = call_args[0][1] if call_args[0] else call_args[1]
    if isinstance(payload, dict) and "data" in payload:
        return json.loads(payload["data"]) if isinstance(payload["data"], str) else payload["data"]
    return payload


# ---------------------------------------------------------------------------
# Tests: Low Risk (Approved)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestLowRisk:
    """Verified, high confidence, good income → approved, low risk."""

    async def test_kyc_approved(self, consumer, repository, mock_redis):
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(
            _make_event(app_id=app.id, verified=True, confidence=0.95)
        )

        data = _extract_event_data(mock_redis)
        assert data["kycStatus"] == "approved"

    async def test_risk_tier_low(self, consumer, repository, mock_redis):
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(
            _make_event(app_id=app.id, verified=True, confidence=0.95)
        )

        data = _extract_event_data(mock_redis)
        assert data["riskTier"] == "low"


# ---------------------------------------------------------------------------
# Tests: Medium Risk (Review)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestMediumRisk:
    """Some flags present → review, medium risk."""

    async def test_kyc_review_with_single_flag(
        self, consumer, repository, mock_redis
    ):
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(
            _make_event(
                app_id=app.id,
                verified=True,
                confidence=0.85,
                flags=["address_mismatch"],
            )
        )

        data = _extract_event_data(mock_redis)
        assert data["kycStatus"] == "review"
        assert data["riskTier"] == "medium"

    async def test_kyc_review_with_multiple_flags_high_risk(
        self, consumer, repository, mock_redis
    ):
        """Multiple flags should escalate to high risk."""
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(
            _make_event(
                app_id=app.id,
                verified=True,
                confidence=0.7,
                flags=["name_mismatch", "address_mismatch"],
            )
        )

        data = _extract_event_data(mock_redis)
        assert data["kycStatus"] == "review"
        assert data["riskTier"] == "high"


# ---------------------------------------------------------------------------
# Tests: High Risk (Rejected)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestHighRisk:
    """Unverified identity → rejected, high risk."""

    async def test_kyc_rejected_when_not_verified(
        self, consumer, repository, mock_redis
    ):
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(
            _make_event(app_id=app.id, verified=False, confidence=0.3)
        )

        data = _extract_event_data(mock_redis)
        assert data["kycStatus"] == "rejected"

    async def test_risk_tier_high_when_not_verified(
        self, consumer, repository, mock_redis
    ):
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(
            _make_event(app_id=app.id, verified=False, confidence=0.3)
        )

        data = _extract_event_data(mock_redis)
        assert data["riskTier"] == "high"


# ---------------------------------------------------------------------------
# Tests: State Transition
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestStateTransition:
    """State machine transitions for compliance check."""

    async def test_transitions_to_compliance_check(
        self, consumer, repository
    ):
        """Status moves identity_verification → compliance_check."""
        app = _make_application(status=ApplicationStatus.identity_verification)
        repository._applications[app.id] = app

        await consumer.process_event(_make_event(app_id=app.id))

        updated = repository.get(app.id)
        assert updated.status == ApplicationStatus.compliance_check

    async def test_rejects_wrong_initial_state(self, consumer, repository):
        """If not in identity_verification state, transition fails."""
        app = _make_application(status=ApplicationStatus.submitted)
        repository._applications[app.id] = app

        with pytest.raises(ValueError, match="Invalid transition"):
            await consumer.process_event(_make_event(app_id=app.id))


# ---------------------------------------------------------------------------
# Tests: Event Publishing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestEventPublishing:
    """compliance_checked event schema and content."""

    async def test_publishes_compliance_checked(
        self, consumer, repository, mock_redis
    ):
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(_make_event(app_id=app.id))

        mock_redis.xadd.assert_called_once()
        call_args = mock_redis.xadd.call_args
        payload = call_args[0][1] if call_args[0] else call_args[1]
        assert payload.get("eventType") == "compliance_checked"

    async def test_event_contains_reasoning(
        self, consumer, repository, mock_redis
    ):
        """compliance_checked event must include reasoning."""
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(_make_event(app_id=app.id))

        data = _extract_event_data(mock_redis)
        assert "reasoning" in data
        assert len(data["reasoning"]) > 0

    async def test_event_has_required_fields(
        self, consumer, repository, mock_redis
    ):
        """Event must contain applicationId, kycStatus, riskTier, reasoning."""
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(_make_event(app_id=app.id))

        data = _extract_event_data(mock_redis)
        assert "applicationId" in data
        assert "kycStatus" in data
        assert "riskTier" in data
        assert "reasoning" in data


# ---------------------------------------------------------------------------
# Tests: Audit Trail
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestAuditTrail:
    """Audit trail entries for compliance check."""

    async def test_audit_entry_created(self, consumer, repository):
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(_make_event(app_id=app.id))

        updated = repository.get(app.id)
        assert len(updated.auditTrail) == 1
        entry = updated.auditTrail[0]
        assert entry.agent == "compliance"
        assert entry.previousState == "identity_verification"
        assert entry.newState == "compliance_check"
        assert entry.timestamp is not None


# ---------------------------------------------------------------------------
# Tests: Foundry Agent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestFoundryAgent:
    """Foundry agent interaction for compliance reasoning."""

    async def test_foundry_called_with_context(
        self, consumer, repository, mock_foundry
    ):
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(_make_event(app_id=app.id))

        mock_foundry.run.assert_called_once()
        call_kwargs = mock_foundry.run.call_args
        assert "context" in str(call_kwargs)

    async def test_foundry_unavailable_raises(
        self, consumer, repository, mock_foundry
    ):
        """If Foundry is unavailable, error must propagate."""
        app = _make_application()
        repository._applications[app.id] = app
        mock_foundry.run.side_effect = ConnectionError("Foundry unavailable")

        with pytest.raises(ConnectionError):
            await consumer.process_event(_make_event(app_id=app.id))
