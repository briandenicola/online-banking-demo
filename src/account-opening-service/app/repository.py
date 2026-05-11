from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Protocol

from .models import (
    ApplicationCreate,
    ApplicationResponse,
    ApplicationStatus,
    AuditEntry,
    DocumentMetadata,
    AgentResult,
)


class ApplicationRepository(Protocol):
    def create(self, payload: ApplicationCreate, user_id: str) -> ApplicationResponse:
        ...

    def get(self, application_id: str) -> ApplicationResponse | None:
        ...

    def get_all(self, status: ApplicationStatus | None = None) -> list[ApplicationResponse]:
        ...

    def update(self, application: ApplicationResponse) -> ApplicationResponse:
        ...

    def add_document(self, application_id: str, document: DocumentMetadata) -> ApplicationResponse | None:
        ...

    def add_agent_result(self, application_id: str, result: AgentResult) -> ApplicationResponse | None:
        ...

    def add_audit_entry(self, application_id: str, entry: AuditEntry) -> ApplicationResponse | None:
        ...


class InMemoryApplicationRepository:
    def __init__(self) -> None:
        self._applications: dict[str, ApplicationResponse] = {}
        self._owners: dict[str, str] = {}

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
        self._applications[application_id] = application
        self._owners[application_id] = user_id
        return application

    def get(self, application_id: str) -> ApplicationResponse | None:
        return self._applications.get(application_id)

    def get_owner(self, application_id: str) -> str | None:
        return self._owners.get(application_id)

    def get_all(self, status: ApplicationStatus | None = None) -> list[ApplicationResponse]:
        applications = list(self._applications.values())
        if status:
            return [app for app in applications if app.status == status]
        return applications

    def update(self, application: ApplicationResponse) -> ApplicationResponse:
        self._applications[application.id] = application
        return application

    def add_document(self, application_id: str, document: DocumentMetadata) -> ApplicationResponse | None:
        application = self._applications.get(application_id)
        if not application:
            return None
        application.documents.append(document)
        application.updatedAt = datetime.now(timezone.utc)
        self._applications[application_id] = application
        return application

    def add_agent_result(self, application_id: str, result: AgentResult) -> ApplicationResponse | None:
        application = self._applications.get(application_id)
        if not application:
            return None
        application.agentResults.append(result)
        application.updatedAt = datetime.now(timezone.utc)
        self._applications[application_id] = application
        return application

    def add_audit_entry(self, application_id: str, entry: AuditEntry) -> ApplicationResponse | None:
        application = self._applications.get(application_id)
        if not application:
            return None
        application.auditTrail.append(entry)
        application.updatedAt = datetime.now(timezone.utc)
        self._applications[application_id] = application
        return application
