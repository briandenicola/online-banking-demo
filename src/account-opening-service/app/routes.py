from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field

from .auth import UserClaims, require_admin, require_auth
from .events import publish_event
from .models import (
    ApplicationCreate,
    ApplicationStatus,
    AuditEntry,
    DocumentMetadata,
    DocumentType,
)
from .repository import InMemoryApplicationRepository
from .state_machine import ApplicationStateMachine

router = APIRouter(prefix="/api/account-opening", tags=["account-opening"])
state_machine = ApplicationStateMachine()


@router.post("/applications", status_code=status.HTTP_201_CREATED)
async def create_application(
    payload: ApplicationCreate,
    request: Request,
    user: Annotated[UserClaims, Depends(require_auth)],
):
    repository: InMemoryApplicationRepository = request.app.state.repository
    application = repository.create(payload, user.user_id)

    await publish_event(
        request.app.state.redis,
        event_type="application_submitted",
        data={
            "applicationId": application.id,
            "userId": user.user_id,
            "status": application.status.value,
        },
    )

    return application


@router.post("/applications/{application_id}/documents", status_code=status.HTTP_201_CREATED)
async def upload_document(
    application_id: str,
    request: Request,
    user: Annotated[UserClaims, Depends(require_auth)],
    document_type: Annotated[DocumentType, Form(alias="documentType")],
    file: UploadFile = File(...),
):
    repository: InMemoryApplicationRepository = request.app.state.repository
    application = repository.get(application_id)
    if not application:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    owner = repository.get_owner(application_id)
    if user.role != "Admin" and owner != user.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    safe_name = file.filename or f"document-{document_type}-{datetime.now(timezone.utc).timestamp()}"
    blob_path = f"{application_id}/{document_type}/{safe_name}"
    container_name = "account-opening-documents"

    blob_service_client = request.app.state.blob_service_client
    if not blob_service_client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Blob storage not configured",
        )

    try:
        blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_path)
        file_content = await file.read()
        blob_client.upload_blob(file_content, overwrite=True)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to upload document to blob storage: {exc}",
        )

    storage_account_name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME", "")
    blob_url = f"https://{storage_account_name}.blob.core.windows.net/{container_name}/{blob_path}"

    metadata = DocumentMetadata(
        type=document_type,
        filename=safe_name,
        uploadedAt=datetime.now(timezone.utc),
        blobUrl=blob_url,
    )

    repository.add_document(application_id, metadata)

    await publish_event(
        request.app.state.redis,
        event_type="document_uploaded",
        data={
            "applicationId": application_id,
            "documentType": document_type,
            "blobUrl": metadata.blobUrl,
            "filename": metadata.filename,
        },
    )

    return metadata


@router.get("/applications/{application_id}")
async def get_application(
    application_id: str,
    request: Request,
    user: Annotated[UserClaims, Depends(require_auth)],
):
    repository: InMemoryApplicationRepository = request.app.state.repository
    application = repository.get(application_id)
    if not application:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    owner = repository.get_owner(application_id)
    if user.role != "Admin" and owner != user.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return application


@router.get("/applications")
async def list_applications(
    request: Request,
    _: Annotated[UserClaims, Depends(require_admin)],
    status: ApplicationStatus | None = None,
):
    repository: InMemoryApplicationRepository = request.app.state.repository
    return repository.get_all(status)


class ReviewRequest(BaseModel):
    decision: str = Field(..., description="approved/rejected/pending_review")
    notes: str | None = None


@router.patch("/applications/{application_id}/review")
async def review_application(
    application_id: str,
    payload: ReviewRequest,
    request: Request,
    admin: Annotated[UserClaims, Depends(require_admin)],
):
    repository: InMemoryApplicationRepository = request.app.state.repository
    application = repository.get(application_id)
    if not application:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    if payload.decision not in {"approved", "rejected", "pending_review"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid decision",
        )
    new_status = ApplicationStatus(payload.decision)
    try:
        application = state_machine.transition(
            application,
            new_status,
            agent_name=admin.user_id,
            details={"action": "manual_review", "notes": payload.notes},
        )
    except ValueError:
        previous_state = application.status.value
        application.status = new_status
        application.auditTrail.append(
            AuditEntry(
                timestamp=datetime.now(timezone.utc),
                agent=admin.user_id,
                action="manual_review",
                details={"notes": payload.notes},
                previousState=previous_state,
                newState=new_status.value,
            )
        )
        application.updatedAt = datetime.now(timezone.utc)

    repository.update(application)

    await publish_event(
        request.app.state.redis,
        event_type="application_decision",
        data={
            "applicationId": application_id,
            "decision": new_status.value,
            "notes": payload.notes,
        },
    )
    return application


@router.get("/applications/{application_id}/audit")
async def get_audit_trail(
    application_id: str,
    request: Request,
    _: Annotated[UserClaims, Depends(require_admin)],
):
    repository: InMemoryApplicationRepository = request.app.state.repository
    application = repository.get(application_id)
    if not application:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    return application.auditTrail
