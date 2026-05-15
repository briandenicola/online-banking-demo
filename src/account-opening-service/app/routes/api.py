from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Annotated, Any

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
    AgentResult,
    ApplicationCreate,
    ApplicationStatus,
    AuditEntry,
    DocumentMetadata,
    DocumentType,
)
from app.repository import ApplicationRepository
from app.services.projection import project_application, project_applications
from app.state_machine import ApplicationStateMachine

router = APIRouter(prefix="/api/account-opening", tags=["account-opening"])
logger = structlog.get_logger("account-opening-routes")


def _latest_agent_result_by_name(application, agent_name: str) -> AgentResult | None:
    latest: AgentResult | None = None
    for result in application.agentResults or []:
        if result.agentName != agent_name:
            continue
        if latest is None:
            latest = result
            continue
        if result.timestamp and (not latest.timestamp or result.timestamp >= latest.timestamp):
            latest = result
    return latest


def _build_resubmit_event_payload(application, failed_stage: str) -> tuple[str, dict[str, Any]]:
    if failed_stage == "document_extraction":
        if not application.documents:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Cannot retry document extraction without uploaded documents",
            )
        latest_doc = sorted(
            application.documents,
            key=lambda d: d.uploadedAt,
            reverse=True,
        )[0]
        return (
            "document_uploaded",
            {
                "applicationId": application.id,
                "documentType": latest_doc.type,
                "blobUrl": latest_doc.blobUrl,
                "filename": latest_doc.filename,
            },
        )

    if failed_stage == "identity_verification":
        extraction = _latest_agent_result_by_name(application, "document-extraction")
        if not extraction:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Cannot retry identity verification without document extraction output",
            )
        findings = extraction.findings or {}
        return (
            "document_extracted",
            {
                "applicationId": application.id,
                "documentType": findings.get("documentType"),
                "extracted": findings.get("extracted") or {},
            },
        )

    if failed_stage == "compliance_check":
        identity = _latest_agent_result_by_name(application, "identity-verification")
        extraction = _latest_agent_result_by_name(application, "document-extraction")
        if not identity:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Cannot retry compliance check without identity verification output",
            )
        findings = identity.findings or {}
        extracted = (extraction.findings or {}).get("extracted") if extraction else {}
        return (
            "identity_verified",
            {
                "applicationId": application.id,
                "verified": findings.get("verified"),
                "confidence": identity.confidence,
                "flags": findings.get("flags", []),
                "reasoning": identity.reasoning,
                "extracted": extracted or {},
            },
        )

    if failed_stage == "provisioning":
        compliance = _latest_agent_result_by_name(application, "compliance-check")
        identity = _latest_agent_result_by_name(application, "identity-verification")
        if not compliance:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Cannot retry provisioning without compliance output",
            )
        compliance_findings = compliance.findings or {}
        identity_findings = identity.findings or {}
        return (
            "compliance_checked",
            {
                "applicationId": application.id,
                "verified": identity_findings.get("verified"),
                "identityConfidence": identity.confidence if identity else None,
                "identityFlags": identity_findings.get("flags", []),
                "kycStatus": compliance_findings.get("kycStatus"),
                "riskTier": compliance_findings.get("riskTier"),
                "flags": compliance_findings.get("flags", []),
                "reasoning": compliance.reasoning,
            },
        )

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"Unknown stage: {failed_stage}",
    )


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

    return project_application(application)


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

    return project_application(application)


@router.get("/applications")
async def list_applications(
    _: Annotated[UserClaims, Depends(require_admin)],
    status: ApplicationStatus | None = None,
    repository: ApplicationRepository = Depends(get_repository),
):
    return project_applications(repository.get_all(status))


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

    return project_application(application)


@router.get("/applications/{application_id}/audit")
async def get_audit_trail(
    application_id: str,
    _: Annotated[UserClaims, Depends(require_admin)],
    repository: ApplicationRepository = Depends(get_repository),
):
    """Retrieve audit trail for an application (admin only)."""
    application = repository.get(application_id)
    if not application:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found",
        )

    return application.auditTrail


@router.post("/applications/{application_id}/resubmit", status_code=status.HTTP_202_ACCEPTED)
async def resubmit_application(
    application_id: str,
    user: Annotated[UserClaims, Depends(require_auth)],
    repository: ApplicationRepository = Depends(get_repository),
    redis_client=Depends(get_redis_client),
):
    """
    Resubmit a failed application to retry from the failed stage.
    Enforces retry cap: max 2 attempts per stage (initial + 1 retry).
    """
    application = repository.get(application_id)
    if not application:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    owner = repository.get_owner(application_id)
    if user.role.lower() != "admin" and owner != user.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Validate application status
    if application.status != ApplicationStatus.failed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Application is not in failed state",
        )

    # Validate lastError exists and is retryable
    if not application.lastError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No error information available for retry",
        )

    if not application.lastError.retryable:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This error is not retryable. Please contact support.",
        )

    # Check retry cap (max 2 attempts per stage: initial + 1 retry)
    failed_stage = application.failedStage or application.lastError.stage
    current_attempts = application.stageAttempts.get(failed_stage, 0)
    
    if current_attempts >= 2:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "retry_cap_exceeded",
                "message": "Maximum retry attempts exceeded. Please contact support for assistance.",
            },
        )

    # Clear failure and resume from failed stage
    try:
        application = repository.clear_stage_failure_for_retry(application_id, failed_stage)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    if not application:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update application",
        )

    event_type, replay_data = _build_resubmit_event_payload(application, failed_stage)

    # Re-publish the event to trigger stage processing
    await publish_event(
        redis_client,
        event_type=event_type,
        data={**replay_data, "resubmit": True, "attempt": current_attempts + 1},
    )

    return {
        "applicationId": application_id,
        "resumedFromStage": failed_stage,
        "attempt": current_attempts + 1,
        "status": application.status.value,
        "message": f"Application resumed from {failed_stage} stage.",
    }
