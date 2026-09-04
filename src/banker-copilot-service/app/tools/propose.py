"""`propose_action` — the sole write affordance in this service.

It does not write. It POSTs a proposal to `authority-service`
(`POST /api/authority/approvals`, see `src/authority-service/Controllers/ApprovalsController.cs`)
and returns that service's answer verbatim to the model, so the agent *knows* it is blocked
pending a human signature and can say so rather than assuming success.

Everything the ladder needs — the rung, the escalators, the required evidence, the payload hash,
the TTL — is computed by `authority-service` from `config/authority-policy.yaml`. None of it is
restated here. This module's entire job is transport plus two refusals:

* ``cosignerId`` is **rejected**, not ignored. It does not exist as a field anywhere in this
  system. Naming a co-signer at proposal time lets the requesting banker choose their own
  reviewer, which converts "a second qualified human must review this" into "*this named
  person* must review this" — the exact self-dealing pattern L2 exists to prevent. The queue
  keys on required seniority, never on a person. Silently dropping the field would let a caller
  send it, read back a successful response, and believe it took effect.
* Any attempt to reach an execution or signing route through this tool is refused, because
  those are `authority-service`'s and require a human identity, not the harness's.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

PROPOSE_PATH = "/api/authority/approvals"

#: Fields accepted from the model, mapped to the ProposeRequest contract. Anything else is
#: refused by name — see `_REFUSED_ARGUMENTS`.
_ALLOWED_ARGUMENTS = frozenset(
    {"actionId", "payload", "evidence", "facts", "agentAssessment", "supersedesApprovalId"}
)

_REFUSED_ARGUMENTS: dict[str, str] = {
    "cosignerId": (
        "'cosignerId' does not exist. Choosing your own reviewer is the self-dealing pattern "
        "dual control exists to prevent; the co-sign queue keys on required seniority, never "
        "on a person."
    ),
    "requiredRung": (
        "The rung is derived by authority-service from the resolved policy. A caller-supplied "
        "rung would be a second, lower authority for the same decision."
    ),
    "requiredSigners": (
        "Signer count is derived from the rung. Supplying it would let a proposal ask for "
        "fewer humans than the ladder requires."
    ),
    "policyVersion": (
        "policyVersion is derived from a content hash of the resolved policy and is bound into "
        "the payload hash. It has exactly one authoritative home."
    ),
    "payloadHash": (
        "The payload hash is computed by authority-service under RFC 8785 canonicalization. A "
        "caller-supplied hash is a signature the signer never saw."
    ),
    "execute": (
        "The harness cannot execute. authority-service is the sole executor of "
        "agent-originated writes, and only after the signatures are in."
    ),
    "status": (
        "Lifecycle status is owned by authority-service. A proposal that names its own status "
        "is asking to skip the ladder."
    ),
}

PROPOSE_TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "actionId": {
            "type": "string",
            "description": (
                "Canonical <domain>.<entity>.<verb> action id, from the authority policy "
                "catalogue exposed at GET /api/authority/policy."
            ),
        },
        "payload": {"type": "object", "description": "The action's parameters."},
        "evidence": {
            "type": "object",
            "description": (
                "Tool results gathered before proposing, keyed by tool id. authority-service "
                "re-validates this against the action's requiredEvidence and rejects an "
                "under-evidenced proposal with 422."
            ),
        },
        "facts": {"type": "object", "description": "Facts the escalators evaluate."},
        "agentAssessment": {
            "type": "object",
            "description": "The agent's recommendation and confidence, shown to the human.",
        },
        "supersedesApprovalId": {
            "type": "string",
            "description": "Set when re-planning replaces an outstanding approval.",
        },
    },
    "required": ["actionId", "payload"],
    "additionalProperties": False,
}


class ProposeRejected(ValueError):
    """A proposal refused before it ever left this service."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ProposeOutcome:
    """Whatever authority-service said, passed back to the model unaltered."""

    status_code: int
    body: dict[str, Any]

    @property
    def admitted(self) -> bool:
        return self.status_code in (200, 201)

    @property
    def approval_id(self) -> str | None:
        return self.body.get("id") or self.body.get("approvalId")


def validate_propose_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    for refused, reason in _REFUSED_ARGUMENTS.items():
        if refused in arguments:
            raise ProposeRejected("refused_field", f"'{refused}' is not accepted: {reason}")

    unknown = sorted(set(arguments) - _ALLOWED_ARGUMENTS)
    if unknown:
        raise ProposeRejected(
            "unknown_field",
            f"propose_action does not accept {unknown}. Its contract is the ProposeRequest "
            "shape owned by authority-service.",
        )

    action_id = str(arguments.get("actionId", "")).strip()
    if not action_id:
        raise ProposeRejected("invalid_arguments", "propose_action requires 'actionId'")

    payload = arguments.get("payload")
    if not isinstance(payload, dict) or not payload:
        raise ProposeRejected(
            "invalid_arguments", "propose_action requires a non-empty 'payload' object"
        )

    return arguments


class AuthorityClient:
    """Thin transport to `authority-service`. Holds no policy knowledge of its own."""

    def __init__(self, base_url: str | None, client: httpx.AsyncClient, timeout_ms: int) -> None:
        self._base_url = base_url
        self._client = client
        self._timeout = timeout_ms / 1000

    @property
    def configured(self) -> bool:
        return bool(self._base_url)

    async def propose(
        self,
        arguments: dict[str, Any],
        bearer_token: str,
        session_id: str,
        agent_id: str,
        correlation_id: str | None = None,
    ) -> ProposeOutcome:
        if not self._base_url:
            raise ProposeRejected(
                "authority_unavailable",
                "AUTHORITY_SERVICE_URL is not configured. The harness has no other write path, "
                "so no action can be proposed — which is the correct failure direction.",
            )

        validate_propose_arguments(arguments)

        body = {
            "actionId": arguments["actionId"],
            "payload": arguments["payload"],
            "evidence": arguments.get("evidence") or {},
            "facts": arguments.get("facts") or {},
            "agentAssessment": arguments.get("agentAssessment"),
            "sessionId": session_id,
            "agentId": agent_id,
            "supersedesApprovalId": arguments.get("supersedesApprovalId"),
        }

        headers = {
            "Authorization": f"Bearer {bearer_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if correlation_id:
            headers["X-Correlation-ID"] = correlation_id

        try:
            response = await self._client.post(
                f"{self._base_url}{PROPOSE_PATH}",
                json=body,
                headers=headers,
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise ProposeRejected("authority_unreachable", f"authority-service: {exc}") from exc

        try:
            parsed = response.json()
        except ValueError:
            parsed = {"error": "unparseable_response", "message": response.text[:500]}

        if not isinstance(parsed, dict):
            parsed = {"result": parsed}

        return ProposeOutcome(status_code=response.status_code, body=parsed)

    async def policy_catalogue(self, bearer_token: str) -> dict[str, Any]:
        """The action catalogue, fetched rather than restated.

        The set of proposable actions is a property of the policy file, which this service does
        not own and must not copy.
        """
        if not self._base_url:
            return {"actions": [], "available": False}

        try:
            response = await self._client.get(
                f"{self._base_url}/api/authority/policy",
                headers={"Authorization": f"Bearer {bearer_token}"},
                timeout=self._timeout,
            )
            if response.status_code >= 400:
                return {"actions": [], "available": False}
            return response.json()
        except (httpx.HTTPError, ValueError):
            return {"actions": [], "available": False}
