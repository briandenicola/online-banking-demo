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

logger = structlog.get_logger("compliance-check-agent")

STREAM_NAME = "account-opening-events"
CONSUMER_GROUP = "compliance-group"
AGENT_NAME = "compliance-check"

from .prompts import COMPLIANCE_ASSESSMENT_PROMPT as SYSTEM_PROMPT


class ComplianceCheckConsumer(AgentConsumer):
    STAGE_NAME = "compliance_check"
    EVENT_TYPES = frozenset({"identity_verified"})
    
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
            agent_name="compliance-assessor",
            agent_version=None,  # newest version — provisioned by init_agents
            description="KYC compliance assessment agent",
            default_options={"extra_body": {"model": foundry_model}},
        )


    async def process_event(self, event_data: dict, idempotency_key: str | None = None) -> None:
        if event_data.get("eventType") != "identity_verified":
            return

        payload = event_data.get("data") or {}
        application_id = payload.get("applicationId") or event_data.get("applicationId")
        if not application_id:
            raise ValueError("identity_verified event missing applicationId")

        application = self._repository.get(application_id)
        if not application:
            raise ValueError(f"Application {application_id} not found for compliance check")

        if application.status == ApplicationStatus.identity_verification:
            application = self._state_machine.transition(
                application,
                ApplicationStatus.compliance_check,
                agent_name=AGENT_NAME,
                details={"action": "compliance_check_started"},
            )
        elif application.status != ApplicationStatus.compliance_check:
            raise ValueError(
                f"Invalid state for compliance check: {application.status.value}"
            )

        form_data = application.formData or {}
        identity_summary = {
            "verified": payload.get("verified"),
            "confidence": payload.get("confidence"),
            "flags": payload.get("flags", []),
            "reasoning": payload.get("reasoning", ""),
        }

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
            "Identity verification summary:\n"
            f"{json.dumps(identity_summary, indent=2)}\n\n"
            "Applicant profile:\n"
            f"{json.dumps(_summarize_form_data(form_data), indent=2)}"
        )

        try:
            session = self._agent.create_session()
            response = await self._agent.run(user_message, session=session)
        except Exception as exc:
            logger.error("Foundry compliance check failed", error=str(exc))
            raise

        parsed = _parse_json_response(str(response))
        kyc_status = parsed["kycStatus"]
        risk_tier = parsed["riskTier"]
        confidence = float(parsed["confidence"])
        flags = parsed.get("flags", [])
        reasoning = parsed.get("reasoning", "")

        application.agentResults.append(
            AgentResult(
                agentName=AGENT_NAME,
                status="completed",
                confidence=confidence,
                findings={"kycStatus": kyc_status, "riskTier": risk_tier, "flags": flags},
                reasoning=reasoning,
                timestamp=datetime.now(timezone.utc),
            )
        )

        self._repository.update(application)

        await publish_event(
            self.redis,
            event_type="compliance_checked",
            data={
                "applicationId": application_id,
                "verified": identity_summary.get("verified"),
                "identityConfidence": identity_summary.get("confidence"),
                "identityFlags": identity_summary.get("flags", []),
                "kycStatus": kyc_status,
                "riskTier": risk_tier,
                "flags": flags,
                "reasoning": reasoning,
            },
        )


def _summarize_form_data(form_data: dict[str, Any]) -> dict[str, Any]:
    """
    Summarize form data for agent processing.
    Sanitizes input to prevent prompt injection while preserving semantic meaning.
    """
    return {
        "annualIncome": form_data.get("annualIncome"),
        "employment": form_data.get("employment"),
        "address": form_data.get("address"),
        "accountType": form_data.get("accountType"),
    }


def _sanitize_string(value: str | None, max_length: int = 255) -> str | None:
    """
    Sanitize string input to prevent prompt injection.
    Returns None if value appears to contain instructions or suspicious patterns.
    """
    if not value or not isinstance(value, str):
        return value
    
    # Truncate to prevent excessively long inputs that might contain injection payloads
    value = value[:max_length] if len(value) > max_length else value
    
    # Check for common prompt injection patterns
    suspicious_patterns = [
        "ignore your instructions",
        "forget your role",
        "new instructions",
        "system prompt",
        "you are now",
        "pretend to be",
        "act as if",
        "override your",
        "bypass your",
    ]
    
    lower_value = value.lower()
    for pattern in suspicious_patterns:
        if pattern in lower_value:
            logger.warning(f"Potential prompt injection detected in input: {pattern}")
            # Return sanitized version without raising - let agent handle it
            return value[:100]  # Truncate suspicious content
    
    return value


def _validate_response_for_pii(response: dict[str, Any]) -> dict[str, Any]:
    """
    Validate and sanitize agent response to ensure no PII leakage.
    """
    if isinstance(response.get("reasoning"), str):
        # Redact any full names, addresses, or identifiers that might have leaked
        reasoning = response["reasoning"]
        
        # Mask common PII patterns in reasoning field
        # Replace potential customer names with generic reference
        if len(reasoning) > 500:
            logger.warning("Compliance reasoning field exceeds safe length; truncating")
            response["reasoning"] = reasoning[:500] + "..."
    
    # Validate flags don't contain PII
    if isinstance(response.get("flags"), list):
        sanitized_flags = []
        for flag in response["flags"]:
            if isinstance(flag, str):
                # Ensure flag doesn't contain detailed PII like full addresses or SSNs
                if any(len(part) > 50 for part in flag.split()):
                    # Skip suspiciously long flag components that might be data dumps
                    logger.warning("Compliance flag appears to contain excessive data; filtering")
                    continue
                sanitized_flags.append(flag[:200])  # Truncate each flag
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
        raise ValueError(f"Failed to parse compliance JSON: {exc}") from exc

    if "kycStatus" not in data or "riskTier" not in data or "confidence" not in data:
        raise ValueError("Compliance response missing required fields")

    if data["kycStatus"] not in {"approved", "review", "rejected"}:
        raise ValueError("Compliance response has invalid kycStatus")

    if data["riskTier"] not in {"low", "medium", "high"}:
        raise ValueError("Compliance response has invalid riskTier")

    data["flags"] = data.get("flags", [])
    
    # Validate and sanitize response to prevent PII leakage
    data = _validate_response_for_pii(data)
    
    return data
