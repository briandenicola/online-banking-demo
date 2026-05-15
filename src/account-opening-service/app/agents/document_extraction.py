from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import structlog

from ..consumer import AgentConsumer
from ..events import publish_event
from ..models import AgentResult, ApplicationStatus
from ..repository import InMemoryApplicationRepository
from ..state_machine import ApplicationStateMachine

logger = structlog.get_logger("document-extraction-agent")

STREAM_NAME = "account-opening-events"
CONSUMER_GROUP = "document-extraction-group"
AGENT_NAME = "document-extraction"
ANALYZER_NAME = "prebuilt-documentSearch"


class DocumentExtractionConsumer(AgentConsumer):
    STAGE_NAME = "document_extraction"
    EVENT_TYPES = frozenset({"document_uploaded"})
    
    def __init__(
        self,
        redis,
        repository: InMemoryApplicationRepository,
        state_machine: ApplicationStateMachine,
        consumer_name: str,
        cus_endpoint: str,
        blob_service_client=None,
        model_deployments: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            redis=redis,
            stream=STREAM_NAME,
            group=CONSUMER_GROUP,
            consumer_name=consumer_name,
        )
        if not cus_endpoint:
            raise RuntimeError("CUS_ENDPOINT is not configured for document extraction")
        if not blob_service_client:
            raise RuntimeError("BlobServiceClient is required for document extraction")

        self._repository = repository
        self._state_machine = state_machine
        self._blob_service_client = blob_service_client

        try:
            from azure.ai.contentunderstanding import ContentUnderstandingClient
            from azure.ai.contentunderstanding.models import AnalysisInput
            from azure.identity import DefaultAzureCredential
        except ImportError as exc:
            logger.error("azure-ai-contentunderstanding is not installed", error=str(exc))
            raise

        self._analysis_input_cls = AnalysisInput
        self._credential = DefaultAzureCredential()
        self._client = ContentUnderstandingClient(
            endpoint=cus_endpoint.rstrip("/"),
            credential=self._credential,
        )
        self._ensure_defaults(model_deployments)

    def _ensure_defaults(self, model_deployments: dict[str, str] | None) -> None:
        try:
            self._client.get_defaults()
            return
        except Exception as exc:
            # New CUS resources may not have defaults initialized yet.
            if "DefaultsNotSet" not in str(exc):
                logger.error("Failed to read CUS defaults", error=str(exc))
                raise

        try:
            if model_deployments:
                self._client.update_defaults({}, model_deployments=model_deployments)
            else:
                self._client.update_defaults({})
            logger.info(
                "Initialized CUS defaults",
                model_deployments_configured=bool(model_deployments),
            )
        except Exception as exc:
            logger.error("Failed to initialize CUS defaults", error=str(exc))
            raise

    async def process_event(self, event_data: dict, idempotency_key: str | None = None) -> None:
        if event_data.get("eventType") != "document_uploaded":
            return

        payload = event_data.get("data") or {}
        application_id = payload.get("applicationId") or event_data.get("applicationId")
        if not application_id:
            raise ValueError("document_uploaded event missing applicationId")

        application = self._repository.get(application_id)
        if not application:
            raise ValueError(f"Application {application_id} not found for document extraction")

        if application.status not in {
            ApplicationStatus.submitted,
            ApplicationStatus.document_extraction,
        }:
            logger.info(
                "Skipping document extraction for already-progressed application",
                application_id=application_id,
                status=application.status.value,
            )
            return

        blob_url = payload.get("blobUrl")
        if not blob_url:
            raise ValueError("document_uploaded event missing blobUrl")

        # Download blob content so CUS doesn't need direct network access
        try:
            parsed = urlparse(blob_url)
            path_parts = parsed.path.lstrip("/").split("/", 1)
            container_name = path_parts[0]
            blob_name = path_parts[1] if len(path_parts) > 1 else ""
            blob_client = self._blob_service_client.get_blob_client(
                container=container_name, blob=blob_name,
            )
            blob_data = blob_client.download_blob().readall()
            logger.info("Downloaded blob for CUS analysis", blob_url=blob_url, size=len(blob_data))
        except Exception as exc:
            logger.error("Failed to download blob", blob_url=blob_url, error=str(exc))
            raise

        # Determine MIME type from filename
        filename = payload.get("filename", "")
        mime_type = "application/pdf"
        if filename.lower().endswith((".jpg", ".jpeg")):
            mime_type = "image/jpeg"
        elif filename.lower().endswith(".png"):
            mime_type = "image/png"

        try:
            poller = self._client.begin_analyze(
                analyzer_id=ANALYZER_NAME,
                inputs=[self._analysis_input_cls(data=blob_data, mime_type=mime_type)],
            )
            analysis = poller.result()
        except Exception as exc:
            logger.error("Content Understanding analyze failed", error=str(exc))
            raise

        extracted = _extract_fields(analysis)
        document_type = payload.get("documentType")

        details = {
            "action": "document_extracted",
            "documentType": document_type,
            "extracted": extracted,
        }

        if application.status == ApplicationStatus.submitted:
            application = self._state_machine.transition(
                application,
                ApplicationStatus.document_extraction,
                agent_name=AGENT_NAME,
                details=details,
            )

        application.agentResults.append(
            AgentResult(
                agentName=AGENT_NAME,
                status="in_progress",
                confidence=0.0,
                findings={"documentType": document_type},
                reasoning=None,
                timestamp=datetime.now(timezone.utc),
            )
        )
        application.agentResults.append(
            AgentResult(
                agentName=AGENT_NAME,
                status="completed",
                confidence=0.9,
                findings={"documentType": document_type, "extracted": extracted},
                reasoning=None,
                timestamp=datetime.now(timezone.utc),
            )
        )

        self._repository.update(application)

        await publish_event(
            self.redis,
            event_type="document_extracted",
            data={
                "applicationId": application_id,
                "documentType": document_type,
                "extracted": extracted,
            },
        )


def _extract_fields(analysis_result: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for name, value in _iter_fields(analysis_result):
        normalized = _normalize_field_name(name)
        if normalized and value not in (None, ""):
            fields[normalized] = value

    return {
        "name": fields.get("name"),
        "dateOfBirth": fields.get("dateOfBirth"),
        "address": fields.get("address"),
        "documentNumber": fields.get("documentNumber"),
        "expiryDate": fields.get("expiryDate"),
    }


def _iter_fields(analysis_result: Any):
    contents = getattr(analysis_result, "contents", None) or []
    for content in contents:
        fields = getattr(content, "fields", None) or []
        for field in fields:
            name = _read_attr(field, "name")
            value = _read_attr(field, "value")
            if name:
                yield name, value

    top_fields = getattr(analysis_result, "fields", None) or []
    for field in top_fields:
        name = _read_attr(field, "name")
        value = _read_attr(field, "value")
        if name:
            yield name, value


def _read_attr(obj: Any, attr: str):
    if isinstance(obj, dict):
        return obj.get(attr) or obj.get(attr.lower())
    return getattr(obj, attr, None)


def _normalize_field_name(name: str | None) -> str | None:
    if not name:
        return None
    key = name.strip().lower().replace(" ", "_")
    mapping = {
        "full_name": "name",
        "name": "name",
        "applicant_name": "name",
        "first_last_name": "name",
        "date_of_birth": "dateOfBirth",
        "dob": "dateOfBirth",
        "birth_date": "dateOfBirth",
        "address": "address",
        "home_address": "address",
        "residential_address": "address",
        "document_number": "documentNumber",
        "id_number": "documentNumber",
        "license_number": "documentNumber",
        "passport_number": "documentNumber",
        "expiry": "expiryDate",
        "expiration_date": "expiryDate",
        "expiry_date": "expiryDate",
    }
    return mapping.get(key)
