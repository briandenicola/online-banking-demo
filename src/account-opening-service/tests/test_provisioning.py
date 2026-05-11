"""Tests for Agent 4: Account Provisioning Consumer (Orchestrator).

Validates that the provisioning agent:
- Auto-approves when verified + approved + low risk
- Routes to review when flags or medium/high risk
- Auto-rejects when verified=false or kycStatus=rejected
- Calls user-service and account-service for approvals
- Handles service call failures gracefully
- Publishes `application_decision` event
- Transitions: compliance_check → approved/rejected/pending_review
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
    app_id: str = "app-prov-001",
    status: ApplicationStatus = ApplicationStatus.compliance_check,
    form_data: dict | None = None,
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
    )


def _make_event(
    app_id: str = "app-prov-001",
    kyc_status: str = "approved",
    risk_tier: str = "low",
    verified: bool = True,
    flags: list[str] | None = None,
) -> dict:
    """Simulate a decoded `compliance_checked` event."""
    return {
        "eventType": "compliance_checked",
        "applicationId": app_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": {
            "applicationId": app_id,
            "kycStatus": kyc_status,
            "riskTier": risk_tier,
            "reasoning": "Compliance assessment complete",
            # These come from aggregated pipeline results
            "verified": verified,
            "flags": flags or [],
        },
    }


# ---------------------------------------------------------------------------
# Provisioning Consumer Stub
# ---------------------------------------------------------------------------

class ProvisioningConsumer(AgentConsumer):
    """Test-side implementation of provisioning consumer."""

    def __init__(
        self,
        redis,
        repository: InMemoryApplicationRepository,
        state_machine: ApplicationStateMachine,
        event_publisher: EventPublisher,
        foundry_agent: AsyncMock | None = None,
        user_service_client: AsyncMock | None = None,
        account_service_client: AsyncMock | None = None,
    ) -> None:
        super().__init__(
            redis=redis,
            stream="account-opening-events",
            group="provisioning-group",
            consumer_name="provisioning-1",
        )
        self.repository = repository
        self.state_machine = state_machine
        self.publisher = event_publisher
        self.foundry_agent = foundry_agent
        self.user_service = user_service_client
        self.account_service = account_service_client

    async def process_event(self, event_data: dict) -> None:
        if event_data.get("eventType") != "compliance_checked":
            return

        data = event_data.get("data", event_data)
        app_id = data.get("applicationId")
        kyc_status = data.get("kycStatus")
        risk_tier = data.get("riskTier")
        verified = data.get("verified", True)
        flags = data.get("flags", [])

        application = self.repository.get(app_id)
        if application is None:
            raise ValueError(f"Application {app_id} not found")

        # Decision logic per spec
        if not verified or kyc_status == "rejected":
            decision = "rejected"
            target_status = ApplicationStatus.rejected
            reasoning = "Application rejected due to failed verification or compliance"
            user_id = None
            account_id = None
        elif flags or kyc_status == "review" or risk_tier in ("medium", "high"):
            decision = "pending_review"
            target_status = ApplicationStatus.pending_review
            reasoning = f"Routed for review: flags={flags}, risk={risk_tier}"
            user_id = None
            account_id = None
        else:
            # Auto-approve path: verified=true, kyc=approved, risk=low
            decision = "approved"
            target_status = ApplicationStatus.approved
            reasoning = "Auto-approved: all checks passed"

            # Call user-service and account-service
            form = application.formData
            user_result = await self.user_service.post(
                "/api/auth/register",
                json={
                    "email": form.get("email"),
                    "password": "temp-generated",
                    "name": f"{form.get('firstName')} {form.get('lastName')}",
                },
            )
            user_id = user_result.get("id") if isinstance(user_result, dict) else None

            account_result = await self.account_service.post(
                "/api/accounts",
                json={
                    "userId": user_id,
                    "accountType": form.get("accountType"),
                    "initialBalance": 0,
                },
            )
            account_id = account_result.get("id") if isinstance(account_result, dict) else None

        # State transition
        self.state_machine.transition(
            application,
            target_status,
            agent_name="provisioning",
            details={
                "action": f"auto_{decision}" if decision != "pending_review" else "route_to_review",
                "decision": decision,
                "reasoning": reasoning,
            },
        )
        self.repository.update(application)

        # Publish event
        await self.publisher.publish(
            stream_name=None,
            event_type="application_decision",
            data={
                "applicationId": app_id,
                "decision": decision,
                "userId": user_id,
                "accountId": account_id,
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
    agent.run = AsyncMock(return_value={"decision": "approved"})
    return agent


@pytest.fixture
def mock_user_service() -> AsyncMock:
    client = AsyncMock()
    client.post = AsyncMock(return_value={"id": "usr-new-001"})
    return client


@pytest.fixture
def mock_account_service() -> AsyncMock:
    client = AsyncMock()
    client.post = AsyncMock(return_value={"id": "acc-new-001"})
    return client


@pytest.fixture
def publisher(mock_redis) -> EventPublisher:
    return EventPublisher(mock_redis)


@pytest.fixture
def consumer(
    mock_redis,
    repository,
    state_machine,
    publisher,
    mock_foundry,
    mock_user_service,
    mock_account_service,
) -> ProvisioningConsumer:
    return ProvisioningConsumer(
        redis=mock_redis,
        repository=repository,
        state_machine=state_machine,
        event_publisher=publisher,
        foundry_agent=mock_foundry,
        user_service_client=mock_user_service,
        account_service_client=mock_account_service,
    )


def _extract_event_data(mock_redis) -> dict:
    call_args = mock_redis.xadd.call_args
    payload = call_args[0][1] if call_args[0] else call_args[1]
    if isinstance(payload, dict) and "data" in payload:
        return json.loads(payload["data"]) if isinstance(payload["data"], str) else payload["data"]
    return payload


# ---------------------------------------------------------------------------
# Tests: Auto-Approve Path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestAutoApprove:
    """verified=true + kycStatus=approved + riskTier=low → approved."""

    async def test_decision_approved(self, consumer, repository, mock_redis):
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(
            _make_event(app_id=app.id, kyc_status="approved", risk_tier="low", verified=True)
        )

        data = _extract_event_data(mock_redis)
        assert data["decision"] == "approved"

    async def test_calls_user_service(
        self, consumer, repository, mock_user_service
    ):
        """Auto-approve must create user via user-service."""
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(
            _make_event(app_id=app.id, kyc_status="approved", risk_tier="low")
        )

        mock_user_service.post.assert_called_once()
        call_args = mock_user_service.post.call_args
        assert "/api/auth/register" in str(call_args)

    async def test_calls_account_service(
        self, consumer, repository, mock_account_service
    ):
        """Auto-approve must create account via account-service."""
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(
            _make_event(app_id=app.id, kyc_status="approved", risk_tier="low")
        )

        mock_account_service.post.assert_called_once()
        call_args = mock_account_service.post.call_args
        assert "/api/accounts" in str(call_args)

    async def test_state_transitions_to_approved(
        self, consumer, repository
    ):
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(
            _make_event(app_id=app.id, kyc_status="approved", risk_tier="low")
        )

        updated = repository.get(app.id)
        assert updated.status == ApplicationStatus.approved

    async def test_event_contains_user_and_account_ids(
        self, consumer, repository, mock_redis
    ):
        """Approved event should include created userId and accountId."""
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(
            _make_event(app_id=app.id, kyc_status="approved", risk_tier="low")
        )

        data = _extract_event_data(mock_redis)
        assert data.get("userId") is not None
        assert data.get("accountId") is not None


# ---------------------------------------------------------------------------
# Tests: Review Path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestReviewPath:
    """Flags present or medium/high risk → pending_review."""

    async def test_flags_route_to_review(self, consumer, repository, mock_redis):
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(
            _make_event(
                app_id=app.id,
                kyc_status="approved",
                risk_tier="low",
                flags=["address_mismatch"],
            )
        )

        data = _extract_event_data(mock_redis)
        assert data["decision"] == "pending_review"

    async def test_review_kyc_status_routes_to_review(
        self, consumer, repository, mock_redis
    ):
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(
            _make_event(app_id=app.id, kyc_status="review", risk_tier="medium")
        )

        data = _extract_event_data(mock_redis)
        assert data["decision"] == "pending_review"

    async def test_medium_risk_routes_to_review(
        self, consumer, repository, mock_redis
    ):
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(
            _make_event(app_id=app.id, kyc_status="approved", risk_tier="medium")
        )

        data = _extract_event_data(mock_redis)
        assert data["decision"] == "pending_review"

    async def test_state_transitions_to_pending_review(
        self, consumer, repository
    ):
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(
            _make_event(
                app_id=app.id,
                kyc_status="review",
                risk_tier="medium",
                flags=["name_mismatch"],
            )
        )

        updated = repository.get(app.id)
        assert updated.status == ApplicationStatus.pending_review

    async def test_no_user_service_call_on_review(
        self, consumer, repository, mock_user_service
    ):
        """Review path must NOT create user or account."""
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(
            _make_event(app_id=app.id, kyc_status="review", risk_tier="medium")
        )

        mock_user_service.post.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: Reject Path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestRejectPath:
    """verified=false or kycStatus=rejected → rejected."""

    async def test_not_verified_rejected(
        self, consumer, repository, mock_redis
    ):
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(
            _make_event(app_id=app.id, verified=False, kyc_status="rejected")
        )

        data = _extract_event_data(mock_redis)
        assert data["decision"] == "rejected"

    async def test_kyc_rejected_status(
        self, consumer, repository, mock_redis
    ):
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(
            _make_event(app_id=app.id, verified=True, kyc_status="rejected")
        )

        data = _extract_event_data(mock_redis)
        assert data["decision"] == "rejected"

    async def test_state_transitions_to_rejected(self, consumer, repository):
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(
            _make_event(app_id=app.id, verified=False, kyc_status="rejected")
        )

        updated = repository.get(app.id)
        assert updated.status == ApplicationStatus.rejected

    async def test_no_user_service_call_on_reject(
        self, consumer, repository, mock_user_service
    ):
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(
            _make_event(app_id=app.id, verified=False)
        )

        mock_user_service.post.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: State Transition Validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestStateTransition:
    """State machine transitions for provisioning."""

    async def test_rejects_wrong_initial_state(self, consumer, repository):
        """If not in compliance_check state, transition fails."""
        app = _make_application(status=ApplicationStatus.submitted)
        repository._applications[app.id] = app

        with pytest.raises(ValueError, match="Invalid transition"):
            await consumer.process_event(_make_event(app_id=app.id))


# ---------------------------------------------------------------------------
# Tests: Event Publishing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestEventPublishing:
    """application_decision event schema."""

    async def test_publishes_application_decision(
        self, consumer, repository, mock_redis
    ):
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(_make_event(app_id=app.id))

        mock_redis.xadd.assert_called_once()
        call_args = mock_redis.xadd.call_args
        payload = call_args[0][1] if call_args[0] else call_args[1]
        assert payload.get("eventType") == "application_decision"

    async def test_event_has_required_fields(
        self, consumer, repository, mock_redis
    ):
        """Event must contain applicationId, decision, reasoning."""
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(_make_event(app_id=app.id))

        data = _extract_event_data(mock_redis)
        assert "applicationId" in data
        assert "decision" in data
        assert "reasoning" in data


# ---------------------------------------------------------------------------
# Tests: Service Call Failures
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestServiceCallFailures:
    """Graceful handling when user-service or account-service fail."""

    async def test_user_service_failure_raises(
        self, consumer, repository, mock_user_service
    ):
        """If user-service is down during auto-approve, error must propagate."""
        app = _make_application()
        repository._applications[app.id] = app
        mock_user_service.post.side_effect = ConnectionError(
            "user-service unavailable"
        )

        with pytest.raises(ConnectionError, match="user-service"):
            await consumer.process_event(
                _make_event(app_id=app.id, kyc_status="approved", risk_tier="low")
            )

    async def test_account_service_failure_raises(
        self, consumer, repository, mock_account_service
    ):
        """If account-service is down during auto-approve, error must propagate."""
        app = _make_application()
        repository._applications[app.id] = app
        mock_account_service.post.side_effect = ConnectionError(
            "account-service unavailable"
        )

        with pytest.raises(ConnectionError, match="account-service"):
            await consumer.process_event(
                _make_event(app_id=app.id, kyc_status="approved", risk_tier="low")
            )


# ---------------------------------------------------------------------------
# Tests: Audit Trail
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestAuditTrail:
    """Audit trail entries for provisioning."""

    async def test_audit_entry_created_on_approve(self, consumer, repository):
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(
            _make_event(app_id=app.id, kyc_status="approved", risk_tier="low")
        )

        updated = repository.get(app.id)
        assert len(updated.auditTrail) == 1
        entry = updated.auditTrail[0]
        assert entry.agent == "provisioning"
        assert entry.previousState == "compliance_check"
        assert entry.newState == "approved"

    async def test_audit_entry_created_on_reject(self, consumer, repository):
        app = _make_application()
        repository._applications[app.id] = app

        await consumer.process_event(
            _make_event(app_id=app.id, verified=False, kyc_status="rejected")
        )

        updated = repository.get(app.id)
        assert len(updated.auditTrail) == 1
        entry = updated.auditTrail[0]
        assert entry.agent == "provisioning"
        assert entry.newState == "rejected"
