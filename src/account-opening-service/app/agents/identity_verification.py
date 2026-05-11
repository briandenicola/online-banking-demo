from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

import structlog

from ..consumer import AgentConsumer
from ..events import publish_event
from ..models import AgentResult, ApplicationStatus
from ..repository import InMemoryApplicationRepository
from ..state_machine import ApplicationStateMachine

logger = structlog.get_logger("identity-verification-agent")

STREAM_NAME = "account-opening-events"
CONSUMER_GROUP = "identity-verification-group"
AGENT_NAME = "identity-verification"

SYSTEM_PROMPT = (
    "You are a bank identity verification agent. Compare extracted document data "
    "against the application form data and determine if the identity is verified.\n\n"
    "Check name, date of birth, and address for mismatches. If there are any "
    "material mismatches, set verified=false and include flags explaining why.\n\n"
    "Return ONLY JSON (no markdown):\n"
    '{'
    '"verified": <true|false>, '
    '"confidence": <float 0.0-1.0>, '
    '"flags": ["<flag>", ...], '
    '"reasoning": "<short explanation>"'
    '}'
)


class IdentityVerificationConsumer(AgentConsumer):
    def __init__(
        self,
        redis,
        repository: InMemoryApplicationRepository,
        state_machine: ApplicationStateMachine,
        consumer_name: str,
        foundry_endpoint: str,
        foundry_model: str,
        credential: "DefaultAzureCredential | None" = None,
    ) -> None:
        super().__init__(
            redis=redis,
            stream=STREAM_NAME,
            group=CONSUMER_GROUP,
            consumer_name=consumer_name,
        )
        if not foundry_endpoint:
            raise RuntimeError("FOUNDRY_PROJECT_ENDPOINT is not configured")

        self._repository = repository
        self._state_machine = state_machine
        self._model = foundry_model

        try:
            from agent_framework_foundry import FoundryAgent
        except ImportError as exc:
            logger.error("agent-framework-foundry is not installed", error=str(exc))
            raise

        if credential is None:
            try:
                from azure.identity import DefaultAzureCredential
            except ImportError as exc:
                logger.error("azure-identity is not installed", error=str(exc))
                raise
            credential = DefaultAzureCredential()

        self._credential = credential
        self._agent = FoundryAgent(
            project_endpoint=foundry_endpoint.rstrip("/"),
            credential=self._credential,
            agent_name="identity-verifier",
            agent_version="1",
            description="Identity verification agent",
            instructions=SYSTEM_PROMPT,
        )


if TYPE_CHECKING:
    from azure.identity import DefaultAzureCredential

    async def process_event(self, event_data: dict) -> None:
        if event_data.get("eventType") != "document_extracted":
            return

        payload = event_data.get("data") or {}
        application_id = payload.get("applicationId") or event_data.get("applicationId")
        if not application_id:
            raise ValueError("document_extracted event missing applicationId")

        application = self._repository.get(application_id)
        if not application:
            raise ValueError(f"Application {application_id} not found for identity verification")

        extracted = payload.get("extracted") or {}
        form_data = application.formData or {}

        user_message = (
            "Application form data:\n"
            f"{json.dumps(_summarize_form_data(form_data), indent=2)}\n\n"
            "Extracted document data:\n"
            f"{json.dumps(extracted, indent=2)}"
        )

        try:
            session = self._agent.create_session()
            response = await self._agent.run(user_message, session=session)
        except Exception as exc:
            logger.error("Foundry identity verification failed", error=str(exc))
            raise

        parsed = _parse_json_response(str(response))
        verified = parsed["verified"]
        confidence = float(parsed["confidence"])
        flags = parsed.get("flags", [])
        reasoning = parsed.get("reasoning", "")

        details = {
            "action": "identity_verified",
            "verified": verified,
            "confidence": confidence,
            "flags": flags,
            "reasoning": reasoning,
        }

        application = self._state_machine.transition(
            application,
            ApplicationStatus.identity_verification,
            agent_name=AGENT_NAME,
            details=details,
        )

        application.agentResults.append(
            AgentResult(
                agentName=AGENT_NAME,
                status="completed",
                confidence=confidence,
                findings={"verified": verified, "flags": flags},
                reasoning=reasoning,
                timestamp=datetime.now(timezone.utc),
            )
        )

        self._repository.update(application)

        await publish_event(
            self.redis,
            event_type="identity_verified",
            data={
                "applicationId": application_id,
                "verified": verified,
                "confidence": confidence,
                "flags": flags,
                "reasoning": reasoning,
                "extracted": extracted,
            },
        )


def _summarize_form_data(form_data: dict[str, Any]) -> dict[str, Any]:
    return {
        "firstName": form_data.get("firstName"),
        "lastName": form_data.get("lastName"),
        "dateOfBirth": form_data.get("dateOfBirth"),
        "address": form_data.get("address"),
    }


def _parse_json_response(response: str) -> dict[str, Any]:
    text = response.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if "\n" in text:
            text = text.split("\n", 1)[1]

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse identity verification JSON: {exc}") from exc

    if "verified" not in data or "confidence" not in data:
        raise ValueError("Identity verification response missing required fields")

    if not isinstance(data["verified"], bool):
        raise ValueError("Identity verification response 'verified' must be boolean")

    data["flags"] = data.get("flags", [])
    return data
