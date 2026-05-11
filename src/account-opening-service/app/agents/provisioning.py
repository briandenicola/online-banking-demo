from __future__ import annotations

import json
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, TYPE_CHECKING

import httpx
import structlog
from jose import jwt

from ..consumer import AgentConsumer
from ..events import publish_event
from ..models import AgentResult, ApplicationStatus
from ..repository import InMemoryApplicationRepository
from ..state_machine import ApplicationStateMachine

logger = structlog.get_logger("provisioning-agent")

STREAM_NAME = "account-opening-events"
CONSUMER_GROUP = "provisioning-group"
AGENT_NAME = "provisioning"

SYSTEM_PROMPT = (
    "You are the account provisioning orchestrator. Based on the compliance "
    "assessment and identity verification results, summarize the decision. "
    "Return ONLY JSON (no markdown):\n"
    '{'
    '"decision": "<approved|rejected|pending_review>", '
    '"confidence": <float 0.0-1.0>, '
    '"flags": ["<flag>", ...], '
    '"reasoning": "<short explanation>"'
    '}'
)


class ProvisioningConsumer(AgentConsumer):
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
            agent_name="account-provisioner",
            agent_version="1",
            description="Account provisioning agent",
            instructions=SYSTEM_PROMPT,
        )

        self._user_service_url = os.getenv(
            "USER_SERVICE_URL", "http://user-service.banking-demo.svc.cluster.local"
        ).rstrip("/")
        self._account_service_url = os.getenv(
            "ACCOUNT_SERVICE_URL", "http://account-service.banking-demo.svc.cluster.local"
        ).rstrip("/")

    async def process_event(self, event_data: dict) -> None:
        if event_data.get("eventType") != "compliance_checked":
            return

        payload = event_data.get("data") or {}
        application_id = payload.get("applicationId") or event_data.get("applicationId")
        if not application_id:
            raise ValueError("compliance_checked event missing applicationId")

        application = self._repository.get(application_id)
        if not application:
            raise ValueError(f"Application {application_id} not found for provisioning")

        verified = payload.get("verified")
        kyc_status = payload.get("kycStatus")
        risk_tier = payload.get("riskTier")
        identity_flags = payload.get("identityFlags", [])
        compliance_flags = payload.get("flags", [])

        user_message = (
            "Compliance summary:\n"
            f"{json.dumps(_summarize_decision_inputs(payload), indent=2)}\n\n"
            "Applicant form data:\n"
            f"{json.dumps(_summarize_form_data(application.formData), indent=2)}"
        )

        try:
            session = self._agent.create_session()
            response = await self._agent.run(user_message, session=session)
        except Exception as exc:
            logger.error("Foundry provisioning decision failed", error=str(exc))
            raise

        agent_output = _parse_json_response(str(response))
        agent_flags = agent_output.get("flags", [])
        reasoning = agent_output.get("reasoning", "")
        confidence = float(agent_output["confidence"])

        combined_flags = _merge_flags(identity_flags, compliance_flags, agent_flags)
        decision = _determine_decision(
            verified=verified,
            kyc_status=kyc_status,
            risk_tier=risk_tier,
            flags=combined_flags,
        )

        details = {
            "action": "application_decision",
            "decision": decision,
            "kycStatus": kyc_status,
            "riskTier": risk_tier,
            "verified": verified,
            "flags": combined_flags,
            "reasoning": reasoning,
        }

        new_status = _decision_to_status(decision)
        application = self._state_machine.transition(
            application,
            new_status,
            agent_name=AGENT_NAME,
            details=details,
        )

        application.agentResults.append(
            AgentResult(
                agentName=AGENT_NAME,
                status="completed",
                confidence=confidence,
                findings={"decision": decision, "flags": combined_flags},
                reasoning=reasoning,
                timestamp=datetime.now(timezone.utc),
            )
        )

        user_id = None
        account_ids: list[str] = []
        if decision == "approved":
            user_id, account_ids = await self._provision_account(application)

        self._repository.update(application)

        await publish_event(
            self.redis,
            event_type="application_decision",
            data={
                "applicationId": application_id,
                "decision": decision,
                "kycStatus": kyc_status,
                "riskTier": risk_tier,
                "verified": verified,
                "flags": combined_flags,
                "reasoning": reasoning,
                "userId": user_id,
                "accountIds": account_ids,
            },
        )

    async def _provision_account(self, application) -> tuple[str, list[str]]:
        password = _generate_password()
        user_payload = _build_user_payload(application.formData, password)

        async with httpx.AsyncClient(timeout=20.0) as client:
            user_resp = await client.post(
                f"{self._user_service_url}/api/auth/register",
                json=user_payload,
            )

            if user_resp.status_code >= 400:
                logger.error(
                    "User registration failed",
                    status=user_resp.status_code,
                    body=user_resp.text[:200],
                )
                user_resp.raise_for_status()

            user_data = user_resp.json() if user_resp.content else {}
            user_id = (
                user_data.get("userId")
                or user_data.get("UserId")
                or user_data.get("id")
                or user_data.get("Id")
            )
            if not user_id:
                raise RuntimeError("User registration response missing userId")

            token = _generate_service_token(user_id, user_payload["username"])
            headers = {"Authorization": f"Bearer {token}", "X-User-Id": user_id}

            account_ids = []
            for account_type in _expand_account_types(application.formData.get("accountType")):
                account_payload = {
                    "accountType": account_type,
                    "initialBalance": 0,
                    "currency": "USD",
                }
                account_resp = await client.post(
                    f"{self._account_service_url}/api/accounts",
                    json=account_payload,
                    headers=headers,
                )
                if account_resp.status_code >= 400:
                    logger.error(
                        "Account provisioning failed",
                        status=account_resp.status_code,
                        body=account_resp.text[:200],
                    )
                    account_resp.raise_for_status()
                account_data = account_resp.json() if account_resp.content else {}
                account_id = account_data.get("id") or account_data.get("Id")
                if account_id:
                    account_ids.append(account_id)

            return user_id, account_ids


def _summarize_decision_inputs(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "verified": payload.get("verified"),
        "kycStatus": payload.get("kycStatus"),
        "riskTier": payload.get("riskTier"),
        "identityFlags": payload.get("identityFlags", []),
        "complianceFlags": payload.get("flags", []),
    }


def _summarize_form_data(form_data: dict[str, Any]) -> dict[str, Any]:
    return {
        "firstName": form_data.get("firstName"),
        "lastName": form_data.get("lastName"),
        "email": form_data.get("email"),
        "accountType": form_data.get("accountType"),
        "annualIncome": form_data.get("annualIncome"),
    }


def _determine_decision(
    verified: bool | None,
    kyc_status: str | None,
    risk_tier: str | None,
    flags: list[str],
) -> str:
    if verified is False or kyc_status == "rejected":
        return "rejected"
    if flags or kyc_status == "review" or risk_tier in {"medium", "high"}:
        return "pending_review"
    if verified and kyc_status == "approved" and risk_tier == "low":
        return "approved"
    return "pending_review"


def _decision_to_status(decision: str) -> ApplicationStatus:
    if decision == "approved":
        return ApplicationStatus.approved
    if decision == "rejected":
        return ApplicationStatus.rejected
    return ApplicationStatus.pending_review


def _parse_json_response(response: str) -> dict[str, Any]:
    text = response.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if "\n" in text:
            text = text.split("\n", 1)[1]

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse provisioning JSON: {exc}") from exc

    if "decision" not in data or "confidence" not in data:
        raise ValueError("Provisioning response missing required fields")
    if data["decision"] not in {"approved", "rejected", "pending_review"}:
        raise ValueError("Provisioning response has invalid decision value")
    return data


def _merge_flags(*flag_sets: list[str]) -> list[str]:
    merged: list[str] = []
    for flags in flag_sets:
        for flag in flags or []:
            if flag and flag not in merged:
                merged.append(flag)
    return merged


def _expand_account_types(account_type: str | None) -> list[str]:
    if account_type == "both":
        return ["checking", "savings"]
    return [account_type or "checking"]


def _generate_password() -> str:
    return secrets.token_urlsafe(12)


def _build_user_payload(form_data: dict[str, Any], password: str) -> dict[str, Any]:
    username = form_data.get("email") or f"user-{uuid.uuid4().hex[:8]}"
    return {
        "username": username,
        "email": form_data.get("email"),
        "password": password,
        "firstName": form_data.get("firstName"),
        "lastName": form_data.get("lastName"),
    }


def _generate_service_token(user_id: str, username: str) -> str:
    secret = os.getenv("Jwt__Key", "YourSuperSecretKeyForJWTTokenGeneration12345")
    issuer = os.getenv("Jwt__Issuer", "user-service")
    audience = os.getenv("Jwt__Audience", "banking-demo")
    expires_in = int(os.getenv("Jwt__ExpiresInMinutes", "60"))

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_in)
    claims = {
        "sub": user_id,
        "unique_name": username,
        "jti": uuid.uuid4().hex,
        "userId": user_id,
        "role": "User",
        "iss": issuer,
        "aud": audience,
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(claims, secret, algorithm="HS256")


if TYPE_CHECKING:
    from azure.identity import DefaultAzureCredential
