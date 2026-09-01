from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

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

from .prompts import IDENTITY_VERIFICATION_PROMPT as SYSTEM_PROMPT


class IdentityVerificationConsumer(AgentConsumer):
    STAGE_NAME = "identity_verification"
    EVENT_TYPES = frozenset({"document_extracted"})
    
    def __init__(
        self,
        redis,
        repository: InMemoryApplicationRepository,
        state_machine: ApplicationStateMachine,
        consumer_name: str,
        foundry_endpoint: str,
        foundry_model: str,
        credential = None,
    ) -> None:
        super().__init__(
            redis=redis,
            stream=STREAM_NAME,
            group=CONSUMER_GROUP,
            consumer_name=consumer_name,
        )
        if not foundry_endpoint:
            raise RuntimeError("FOUNDRY_PROJECT_ENDPOINT is not configured")
        if credential is None:
            raise RuntimeError("credential is required — caller must supply a TokenCredential")

        self._repository = repository
        self._state_machine = state_machine
        self._model = foundry_model

        try:
            from agent_framework_foundry import FoundryAgent
        except ImportError as exc:
            logger.error("agent-framework-foundry is not installed", error=str(exc))
            raise

        self._credential = credential
        self._agent = FoundryAgent(
            project_endpoint=foundry_endpoint.rstrip("/"),
            credential=self._credential,
            agent_name="identity-verifier",
            agent_version=None,  # newest version — provisioned by init_agents
            description="Identity verification agent",
            default_options={"extra_body": {"model": foundry_model}},
        )


    async def process_event(self, event_data: dict, idempotency_key: str | None = None) -> None:
        if event_data.get("eventType") != "document_extracted":
            return

        payload = event_data.get("data") or {}
        application_id = payload.get("applicationId") or event_data.get("applicationId")
        if not application_id:
            raise ValueError("document_extracted event missing applicationId")

        application = self._repository.get(application_id)
        if not application:
            raise ValueError(f"Application {application_id} not found for identity verification")

        if application.status == ApplicationStatus.document_extraction:
            application = self._state_machine.transition(
                application,
                ApplicationStatus.identity_verification,
                agent_name=AGENT_NAME,
                details={"action": "identity_verification_started"},
            )
        elif application.status != ApplicationStatus.identity_verification:
            raise ValueError(
                f"Invalid state for identity verification: {application.status.value}"
            )

        extracted = payload.get("extracted") or {}
        form_data = application.formData or {}

        application.agentResults.append(
            AgentResult(
                agentName=AGENT_NAME,
                status="in_progress",
                confidence=0.0,
                findings={},
                reasoning=None,
                timestamp=datetime.now(timezone.utc),
            )
        )
        self._repository.update(application)

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
    """
    Summarize form data for identity verification comparison.
    Returns only data needed for field comparison, stripped of extraneous info.
    """
    return {
        "firstName": form_data.get("firstName"),
        "lastName": form_data.get("lastName"),
        "dateOfBirth": form_data.get("dateOfBirth"),
        "address": form_data.get("address"),
    }


def _validate_verification_response(response: dict[str, Any]) -> dict[str, Any]:
    """
    Validate and sanitize identity verification response to prevent PII leakage.
    """
    # Ensure reasoning field doesn't contain echoed PII
    if isinstance(response.get("reasoning"), str):
        reasoning = response["reasoning"]
        
        # Truncate excessively long reasoning that might contain data dumps
        if len(reasoning) > 300:
            logger.warning("Identity verification reasoning exceeds safe length; truncating")
            response["reasoning"] = reasoning[:300] + "..."
        
        # Check for patterns that suggest echoed customer data
        # (e.g., repeated names or addresses in reasoning)
        suspicious_phrases = [
            "matches exactly",
            "verified as",
            "applicant name is",
            "address is",
        ]
        
        lower_reasoning = reasoning.lower()
        for phrase in suspicious_phrases:
            if phrase in lower_reasoning and reasoning.count(" ") > 20:
                # This looks like it might be echoing data; truncate
                logger.warning("Identity verification reasoning may contain echoed PII; truncating")
                response["reasoning"] = response["reasoning"][:150] + "..."
                break
    
    # Validate and sanitize flags
    if isinstance(response.get("flags"), list):
        sanitized_flags = []
        for flag in response["flags"]:
            if isinstance(flag, str):
                # Flags should be generic, not contain specific values
                if any(char.isdigit() for char in flag) and len(flag) > 50:
                    # Likely contains echoed data; truncate
                    logger.warning("Identity flag appears to contain excessive data; filtering")
                    continue
                sanitized_flags.append(flag[:150])  # Truncate each flag
        response["flags"] = sanitized_flags
    
    return response


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
    
    # Validate and sanitize response to prevent PII leakage
    data = _validate_verification_response(data)
    
    return data
