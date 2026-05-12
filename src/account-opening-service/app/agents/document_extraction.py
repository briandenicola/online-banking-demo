from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

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
    def __init__(
        self,
        redis,
        repository: InMemoryApplicationRepository,
        state_machine: ApplicationStateMachine,
        consumer_name: str,
        cus_endpoint: str,
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

        self._repository = repository
        self._state_machine = state_machine

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
        if model_deployments:
            try:
                self._client.update_defaults(model_deployments=model_deployments)
            except Exception as exc:
                logger.warning("Failed to set CUS model deployments", error=str(exc))

    async def process_event(self, event_data: dict) -> None:
        if event_data.get("eventType") != "document_uploaded":
            return

        payload = event_data.get("data") or {}
        application_id = payload.get("applicationId") or event_data.get("applicationId")
        if not application_id:
            raise ValueError("document_uploaded event missing applicationId")

        application = self._repository.get(application_id)
        if not application:
            raise ValueError(f"Application {application_id} not found for document extraction")

        blob_url = payload.get("blobUrl")
        if not blob_url:
            raise ValueError("document_uploaded event missing blobUrl")

        try:
            poller = self._client.begin_analyze(
                analyzer_id=ANALYZER_NAME,
                inputs=[self._analysis_input_cls(url=blob_url)],
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

        application = self._state_machine.transition(
            application,
            ApplicationStatus.document_extraction,
            agent_name=AGENT_NAME,
            details=details,
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
