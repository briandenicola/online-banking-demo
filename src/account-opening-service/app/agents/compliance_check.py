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

logger = structlog.get_logger("compliance-check-agent")

STREAM_NAME = "account-opening-events"
CONSUMER_GROUP = "compliance-group"
AGENT_NAME = "compliance-check"

SYSTEM_PROMPT = (
    "You are a KYC compliance officer at a bank. Evaluate the customer's risk tier "
    "and KYC status using the identity verification result, income, employment, "
    "and standard compliance rules.\n\n"
    "Return ONLY JSON (no markdown):\n"
    '{'
    '"kycStatus": "<approved|review|rejected>", '
    '"riskTier": "<low|medium|high>", '
    '"confidence": <float 0.0-1.0>, '
    '"flags": ["<flag>", ...], '
    '"reasoning": "<short explanation>"'
    '}'
)


class ComplianceCheckConsumer(AgentConsumer):
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
            agent_name="compliance-assessor",
            agent_version="1",
            description="KYC compliance assessment agent",
            instructions=SYSTEM_PROMPT,
        )


if TYPE_CHECKING:
    from azure.identity import DefaultAzureCredential

    async def process_event(self, event_data: dict) -> None:
        if event_data.get("eventType") != "identity_verified":
            return

        payload = event_data.get("data") or {}
        application_id = payload.get("applicationId") or event_data.get("applicationId")
        if not application_id:
            raise ValueError("identity_verified event missing applicationId")

        application = self._repository.get(application_id)
        if not application:
            raise ValueError(f"Application {application_id} not found for compliance check")

        form_data = application.formData or {}
        identity_summary = {
            "verified": payload.get("verified"),
            "confidence": payload.get("confidence"),
            "flags": payload.get("flags", []),
            "reasoning": payload.get("reasoning", ""),
        }

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

        details = {
            "action": "compliance_checked",
            "kycStatus": kyc_status,
            "riskTier": risk_tier,
            "confidence": confidence,
            "flags": flags,
            "reasoning": reasoning,
        }

        application = self._state_machine.transition(
            application,
            ApplicationStatus.compliance_check,
            agent_name=AGENT_NAME,
            details=details,
        )

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
    return {
        "annualIncome": form_data.get("annualIncome"),
        "employment": form_data.get("employment"),
        "address": form_data.get("address"),
        "accountType": form_data.get("accountType"),
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
        raise ValueError(f"Failed to parse compliance JSON: {exc}") from exc

    if "kycStatus" not in data or "riskTier" not in data or "confidence" not in data:
        raise ValueError("Compliance response missing required fields")

    if data["kycStatus"] not in {"approved", "review", "rejected"}:
        raise ValueError("Compliance response has invalid kycStatus")

    if data["riskTier"] not in {"low", "medium", "high"}:
        raise ValueError("Compliance response has invalid riskTier")

    data["flags"] = data.get("flags", [])
    return data
