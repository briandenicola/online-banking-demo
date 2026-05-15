from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from .models import (
    AgentResult,
    ApplicationCreate,
    ApplicationResponse,
    ApplicationStatus,
    AuditEntry,
    DocumentMetadata,
    LastError,
)

logger = structlog.get_logger("cosmos-repository")


class CosmosDBApplicationRepository:
    def __init__(self, container) -> None:
        self._container = container

    def create(self, payload: ApplicationCreate, user_id: str) -> ApplicationResponse:
        now = datetime.now(timezone.utc)
        application_id = str(uuid.uuid4())
        application = ApplicationResponse(
            id=application_id,
            status=ApplicationStatus.submitted,
            createdAt=now,
            updatedAt=now,
            formData=payload.model_dump(),
            documents=[],
            agentResults=[],
            auditTrail=[],
        )

        doc = _to_cosmos_doc(application, user_id)
        self._container.upsert_item(doc)

        return application

    def get(self, application_id: str) -> ApplicationResponse | None:
        try:
            doc = self._container.read_item(
                item=application_id,
                partition_key=application_id,
            )
        except Exception:
            return None
        return _from_cosmos_doc(doc)

    def get_owner(self, application_id: str) -> str | None:
        try:
            doc = self._container.read_item(
                item=application_id,
                partition_key=application_id,
            )
        except Exception:
            return None
        return doc.get("userId")

    def get_all(self, status: ApplicationStatus | None = None) -> list[ApplicationResponse]:
        if status:
            query = "SELECT * FROM c WHERE c.status = @status"
            params: list[dict[str, Any]] = [{"name": "@status", "value": status.value}]
            items = list(self._container.query_items(query=query, parameters=params, enable_cross_partition_query=True))
        else:
            items = list(self._container.query_items(query="SELECT * FROM c", enable_cross_partition_query=True))
        return [_from_cosmos_doc(doc) for doc in items]

    def update(self, application: ApplicationResponse) -> ApplicationResponse:
        try:
            existing = self._container.read_item(
                item=application.id,
                partition_key=application.id,
            )
            user_id = existing.get("userId", "unknown")
        except Exception:
            user_id = "unknown"

        doc = _to_cosmos_doc(application, user_id)
        self._container.upsert_item(doc)
        return application

    def add_document(self, application_id: str, document: DocumentMetadata) -> ApplicationResponse | None:
        application = self.get(application_id)
        if not application:
            return None
        application.documents.append(document)
        application.updatedAt = datetime.now(timezone.utc)
        self.update(application)
        return application

    def add_agent_result(self, application_id: str, result: AgentResult) -> ApplicationResponse | None:
        application = self.get(application_id)
        if not application:
            return None
        application.agentResults.append(result)
        application.updatedAt = datetime.now(timezone.utc)
        self.update(application)
        return application

    def add_audit_entry(self, application_id: str, entry: AuditEntry) -> ApplicationResponse | None:
        application = self.get(application_id)
        if not application:
            return None
        application.auditTrail.append(entry)
        application.updatedAt = datetime.now(timezone.utc)
        self.update(application)
        return application

    def record_stage_failure(
        self,
        application_id: str,
        stage: str,
        error: LastError,
    ) -> ApplicationResponse | None:
        """Record stage failure with error details and increment attempt counter."""
        application = self.get(application_id)
        if not application:
            return None
        
        application.lastError = error
        application.failedStage = stage
        application.status = ApplicationStatus.failed
        
        # Increment stage attempts
        current_attempts = application.stageAttempts.get(stage, 0)
        application.stageAttempts[stage] = current_attempts + 1
        
        application.updatedAt = datetime.now(timezone.utc)
        self.update(application)
        return application

    def clear_stage_failure_for_retry(
        self,
        application_id: str,
        stage: str,
    ) -> ApplicationResponse | None:
        """Clear failure state and resume from failed stage (resubmit)."""
        application = self.get(application_id)
        if not application:
            return None

        resume_status_map = {
            "document_extraction": ApplicationStatus.document_extraction,
            "identity_verification": ApplicationStatus.identity_verification,
            "compliance_check": ApplicationStatus.compliance_check,
            # Provisioning is triggered from the compliance-check checkpoint.
            "provisioning": ApplicationStatus.compliance_check,
        }
        resume_status = resume_status_map.get(stage)
        if resume_status is None:
            raise ValueError(f"Unknown stage: {stage}")

        application.lastError = None
        application.failedStage = None
        application.status = resume_status
        application.updatedAt = datetime.now(timezone.utc)

        self.update(application)
        return application

    def set_customer_explanation(
        self,
        application_id: str,
        outcome: str,
        explanation: str,
    ) -> ApplicationResponse | None:
        """Set customer-facing explanation for terminal state."""
        application = self.get(application_id)
        if not application:
            return None
        
        application.customerOutcome = outcome
        application.customerExplanation = explanation
        application.customerExplanationGeneratedAt = datetime.now(timezone.utc)
        application.updatedAt = datetime.now(timezone.utc)
        
        self.update(application)
        return application


def _to_cosmos_doc(application: ApplicationResponse, user_id: str) -> dict[str, Any]:
    data = application.model_dump(mode="json")
    data["userId"] = user_id
    return data


def _from_cosmos_doc(doc: dict[str, Any]) -> ApplicationResponse:
    return ApplicationResponse.model_validate(doc)
