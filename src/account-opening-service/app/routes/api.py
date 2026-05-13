from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app.auth import UserClaims, require_admin, require_auth
from app.dependencies import (
    get_blob_service_client,
    get_redis_client,
    get_repository,
    get_state_machine,
)
from app.events import publish_event
from app.models import (
    ApplicationCreate,
    ApplicationStatus,
    AuditEntry,
    DocumentMetadata,
    DocumentType,
)
from app.repository import ApplicationRepository
from app.state_machine import ApplicationStateMachine

router = APIRouter(prefix="/api/account-opening", tags=["account-opening"])
logger = structlog.get_logger("account-opening-routes")


@router.post("/applications", status_code=status.HTTP_201_CREATED)
async def create_application(
    payload: ApplicationCreate,
    user: Annotated[UserClaims, Depends(require_auth)],
    repository: ApplicationRepository = Depends(get_repository),
    redis_client=Depends(get_redis_client),
):
    application = repository.create(payload, user.user_id)

    await publish_event(
        redis_client,
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
    user: Annotated[UserClaims, Depends(require_auth)],
    document_type: Annotated[DocumentType, Form(alias="documentType")],
    file: UploadFile = File(...),
    repository: ApplicationRepository = Depends(get_repository),
    redis_client=Depends(get_redis_client),
    blob_service_client=Depends(get_blob_service_client),
):
    application = repository.get(application_id)
    if not application:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    owner = repository.get_owner(application_id)
    if user.role.lower() != "admin" and owner != user.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    safe_name = file.filename or f"document-{document_type}-{datetime.now(timezone.utc).timestamp()}"
    blob_path = f"{application_id}/{document_type}/{safe_name}"
    container_name = "account-opening-documents"

    if not blob_service_client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Blob storage not configured",
        )

    try:
        blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_path)
        file_content = await file.read()
        await asyncio.to_thread(blob_client.upload_blob, file_content, overwrite=True)
    except (ConnectionError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to upload document to blob storage: {exc}",
        )
    except Exception as exc:
        logger.error("Unexpected blob upload error", error=str(exc), exc_info=True)
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
        redis_client,
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
    user: Annotated[UserClaims, Depends(require_auth)],
    repository: ApplicationRepository = Depends(get_repository),
):
    application = repository.get(application_id)
    if not application:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    owner = repository.get_owner(application_id)
    if user.role.lower() != "admin" and owner != user.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return application


@router.get("/applications")
async def list_applications(
    _: Annotated[UserClaims, Depends(require_admin)],
    status: ApplicationStatus | None = None,
    repository: ApplicationRepository = Depends(get_repository),
):
    return repository.get_all(status)


class ReviewRequest(BaseModel):
    decision: str = Field(..., pattern=r"^(approved|rejected|pending_review)$", description="approved/rejected/pending_review")
    notes: str | None = Field(default=None, max_length=2000)


@router.patch("/applications/{application_id}/review")
async def review_application(
    application_id: str,
    payload: ReviewRequest,
    admin: Annotated[UserClaims, Depends(require_admin)],
    repository: ApplicationRepository = Depends(get_repository),
    redis_client=Depends(get_redis_client),
    state_machine: ApplicationStateMachine = Depends(get_state_machine),
):
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
        redis_client,
        event_type="application_decision",
        data={
            "applicationId": application_id,
            "status": new_status.value,
            "agent": admin.user_id,
        },
    )

    return application
