"""Tests for the application state machine.

The state machine governs transitions through the KYC pipeline:
  submitted → document_extraction → identity_verification →
  compliance_check → approved | rejected | pending_review

Invalid transitions (skipping steps, going backwards) must be rejected.
Each transition must append an audit trail entry.
"""
import pytest


class TestValidTransitions:
    """Verify every legal state transition succeeds."""

    def test_submitted_to_document_extraction(self):
        """First pipeline step: submitted → document_extraction."""
        from app.models import ApplicationStatus
        from app.state_machine import transition

        result = transition(
            ApplicationStatus.submitted,
            ApplicationStatus.document_extraction,
            agent="document-extraction",
            action="begin_extraction",
        )
        assert result.new_state == ApplicationStatus.document_extraction

    def test_document_extraction_to_identity_verification(self):
        """Second pipeline step: document_extraction → identity_verification."""
        from app.models import ApplicationStatus
        from app.state_machine import transition

        result = transition(
            ApplicationStatus.document_extraction,
            ApplicationStatus.identity_verification,
            agent="identity-verification",
            action="begin_verification",
        )
        assert result.new_state == ApplicationStatus.identity_verification

    def test_identity_verification_to_compliance_check(self):
        """Third pipeline step: identity_verification → compliance_check."""
        from app.models import ApplicationStatus
        from app.state_machine import transition

        result = transition(
            ApplicationStatus.identity_verification,
            ApplicationStatus.compliance_check,
            agent="compliance",
            action="begin_compliance",
        )
        assert result.new_state == ApplicationStatus.compliance_check

    def test_compliance_check_to_approved(self):
        """Terminal happy path: compliance_check → approved."""
        from app.models import ApplicationStatus
        from app.state_machine import transition

        result = transition(
            ApplicationStatus.compliance_check,
            ApplicationStatus.approved,
            agent="provisioning",
            action="auto_approve",
        )
        assert result.new_state == ApplicationStatus.approved

    def test_compliance_check_to_rejected(self):
        """Terminal rejection: compliance_check → rejected."""
        from app.models import ApplicationStatus
        from app.state_machine import transition

        result = transition(
            ApplicationStatus.compliance_check,
            ApplicationStatus.rejected,
            agent="provisioning",
            action="auto_reject",
        )
        assert result.new_state == ApplicationStatus.rejected

    def test_compliance_check_to_pending_review(self):
        """Flagged for human review: compliance_check → pending_review."""
        from app.models import ApplicationStatus
        from app.state_machine import transition

        result = transition(
            ApplicationStatus.compliance_check,
            ApplicationStatus.pending_review,
            agent="provisioning",
            action="route_to_review",
        )
        assert result.new_state == ApplicationStatus.pending_review

    def test_pending_review_to_approved(self):
        """Admin approves after review: pending_review → approved."""
        from app.models import ApplicationStatus
        from app.state_machine import transition

        result = transition(
            ApplicationStatus.pending_review,
            ApplicationStatus.approved,
            agent="admin",
            action="manual_approve",
        )
        assert result.new_state == ApplicationStatus.approved

    def test_pending_review_to_rejected(self):
        """Admin rejects after review: pending_review → rejected."""
        from app.models import ApplicationStatus
        from app.state_machine import transition

        result = transition(
            ApplicationStatus.pending_review,
            ApplicationStatus.rejected,
            agent="admin",
            action="manual_reject",
        )
        assert result.new_state == ApplicationStatus.rejected


class TestInvalidTransitions:
    """Verify that illegal transitions are rejected with ValueError."""

    def test_cannot_skip_from_submitted_to_approved(self):
        """Skipping the entire pipeline is not allowed."""
        from app.models import ApplicationStatus
        from app.state_machine import transition

        with pytest.raises(ValueError):
            transition(
                ApplicationStatus.submitted,
                ApplicationStatus.approved,
                agent="test",
                action="skip",
            )

    def test_cannot_skip_from_submitted_to_compliance_check(self):
        """Skipping intermediate steps is not allowed."""
        from app.models import ApplicationStatus
        from app.state_machine import transition

        with pytest.raises(ValueError):
            transition(
                ApplicationStatus.submitted,
                ApplicationStatus.compliance_check,
                agent="test",
                action="skip",
            )

    def test_cannot_go_backwards_approved_to_submitted(self):
        """Backwards transitions are not allowed."""
        from app.models import ApplicationStatus
        from app.state_machine import transition

        with pytest.raises(ValueError):
            transition(
                ApplicationStatus.approved,
                ApplicationStatus.submitted,
                agent="test",
                action="rollback",
            )

    def test_cannot_go_backwards_identity_to_document(self):
        """Reversing pipeline order is not allowed."""
        from app.models import ApplicationStatus
        from app.state_machine import transition

        with pytest.raises(ValueError):
            transition(
                ApplicationStatus.identity_verification,
                ApplicationStatus.document_extraction,
                agent="test",
                action="rollback",
            )

    def test_cannot_transition_from_rejected(self):
        """Rejected is a terminal state — no further transitions."""
        from app.models import ApplicationStatus
        from app.state_machine import transition

        with pytest.raises(ValueError):
            transition(
                ApplicationStatus.rejected,
                ApplicationStatus.submitted,
                agent="test",
                action="reopen",
            )

    def test_cannot_transition_from_approved_to_rejected(self):
        """Approved is a terminal state — cannot reject afterwards."""
        from app.models import ApplicationStatus
        from app.state_machine import transition

        with pytest.raises(ValueError):
            transition(
                ApplicationStatus.approved,
                ApplicationStatus.rejected,
                agent="test",
                action="revoke",
            )

    def test_self_transition_not_allowed(self):
        """Transitioning to the same state is not meaningful."""
        from app.models import ApplicationStatus
        from app.state_machine import transition

        with pytest.raises(ValueError):
            transition(
                ApplicationStatus.submitted,
                ApplicationStatus.submitted,
                agent="test",
                action="noop",
            )


class TestAuditTrail:
    """Verify that transitions produce correct audit trail entries."""

    def test_transition_returns_audit_entry(self):
        """Each transition must produce an AuditEntry."""
        from app.models import ApplicationStatus
        from app.state_machine import transition

        result = transition(
            ApplicationStatus.submitted,
            ApplicationStatus.document_extraction,
            agent="document-extraction",
            action="begin_extraction",
        )
        assert result.audit_entry is not None

    def test_audit_entry_contains_timestamp(self):
        """Audit entry must include a timestamp."""
        from app.models import ApplicationStatus
        from app.state_machine import transition

        result = transition(
            ApplicationStatus.submitted,
            ApplicationStatus.document_extraction,
            agent="document-extraction",
            action="begin_extraction",
        )
        assert result.audit_entry.timestamp is not None

    def test_audit_entry_contains_agent_name(self):
        """Audit entry must record which agent performed the transition."""
        from app.models import ApplicationStatus
        from app.state_machine import transition

        result = transition(
            ApplicationStatus.submitted,
            ApplicationStatus.document_extraction,
            agent="document-extraction",
            action="begin_extraction",
        )
        assert result.audit_entry.agent == "document-extraction"

    def test_audit_entry_contains_action(self):
        """Audit entry must record the action performed."""
        from app.models import ApplicationStatus
        from app.state_machine import transition

        result = transition(
            ApplicationStatus.submitted,
            ApplicationStatus.document_extraction,
            agent="document-extraction",
            action="begin_extraction",
        )
        assert result.audit_entry.action == "begin_extraction"

    def test_audit_entry_contains_previous_state(self):
        """Audit entry must record the state before transition."""
        from app.models import ApplicationStatus
        from app.state_machine import transition

        result = transition(
            ApplicationStatus.submitted,
            ApplicationStatus.document_extraction,
            agent="document-extraction",
            action="begin_extraction",
        )
        assert result.audit_entry.previousState == "submitted"

    def test_audit_entry_contains_new_state(self):
        """Audit entry must record the state after transition."""
        from app.models import ApplicationStatus
        from app.state_machine import transition

        result = transition(
            ApplicationStatus.submitted,
            ApplicationStatus.document_extraction,
            agent="document-extraction",
            action="begin_extraction",
        )
        assert result.audit_entry.newState == "document_extraction"
