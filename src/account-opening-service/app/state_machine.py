from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .models import ApplicationResponse, ApplicationStatus, AuditEntry


VALID_TRANSITIONS: dict[ApplicationStatus, set[ApplicationStatus]] = {
    ApplicationStatus.submitted: {ApplicationStatus.document_extraction},
    ApplicationStatus.document_extraction: {ApplicationStatus.identity_verification},
    ApplicationStatus.identity_verification: {ApplicationStatus.compliance_check},
    ApplicationStatus.compliance_check: {
        ApplicationStatus.approved,
        ApplicationStatus.rejected,
        ApplicationStatus.pending_review,
    },
    ApplicationStatus.pending_review: {ApplicationStatus.approved, ApplicationStatus.rejected},
}


@dataclass
class TransitionResult:
    new_state: ApplicationStatus
    audit_entry: AuditEntry


def transition(
    current_state: ApplicationStatus,
    new_state: ApplicationStatus,
    agent: str,
    action: str,
) -> TransitionResult:
    if current_state == new_state:
        raise ValueError("State transition must move to a new state")

    allowed = VALID_TRANSITIONS.get(current_state, set())
    if new_state not in allowed:
        raise ValueError(f"Invalid transition: {current_state} -> {new_state}")

    audit_entry = AuditEntry(
        timestamp=datetime.now(timezone.utc),
        agent=agent,
        action=action,
        previousState=current_state.value,
        newState=new_state.value,
    )
    return TransitionResult(new_state=new_state, audit_entry=audit_entry)


class ApplicationStateMachine:
    def transition(
        self,
        application: ApplicationResponse,
        new_status: ApplicationStatus,
        agent_name: str,
        details: dict | None = None,
    ) -> ApplicationResponse:
        result = transition(
            application.status,
            new_status,
            agent=agent_name,
            action=(details or {}).get("action", "transition"),
        )
        application.status = result.new_state
        application.auditTrail.append(
            AuditEntry(
                timestamp=result.audit_entry.timestamp,
                agent=agent_name,
                action=result.audit_entry.action,
                details=details,
                previousState=result.audit_entry.previousState,
                newState=result.audit_entry.newState,
            )
        )
        application.updatedAt = datetime.now(timezone.utc)
        return application
