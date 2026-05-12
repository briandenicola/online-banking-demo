"""
SidecarTokenCredential — Azure TokenCredential backed by the Entra Agent ID
auth-sidecar that runs as a container in the same Kubernetes pod.

The sidecar exposes:
    GET http://{host}/AuthorizationHeaderUnauthenticated/{api_name}
        ?AgentIdentity={agent_identity}
and returns JSON with an ``Authorization`` field containing a bearer token.
"""

from __future__ import annotations

import base64
import json
import time

import httpx
import structlog
from azure.core.credentials import AccessToken

logger = structlog.get_logger("sidecar-credential")

_MAX_RETRIES = 3
_BACKOFF_BASE = 2  # seconds


class SidecarTokenCredential:
    """Drop-in ``TokenCredential`` that fetches tokens from the Entra Agent ID
    auth-sidecar running alongside the pod."""

    def __init__(
        self,
        sidecar_url: str = "http://localhost:5000",
        agent_identity: str | None = None,
        api_name: str = "ai",
    ) -> None:
        if not agent_identity:
            raise ValueError(
                "agent_identity is required (set AGENT_ID_AGENT_IDENTITY env var)"
            )
        self._sidecar_url = sidecar_url.rstrip("/")
        self._agent_identity = agent_identity
        self._api_name = api_name

    # -- Azure TokenCredential protocol ------------------------------------

    def get_token(
        self,
        *scopes: str,
        **kwargs,
    ) -> AccessToken:
        """Synchronous token fetch with retry/backoff."""
        last_exc: Exception | None = None

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                token, expires_on = self._fetch_token()
                logger.info(
                    "sidecar_token_acquired",
                    attempt=attempt,
                    expires_on=expires_on,
                )
                return AccessToken(token, expires_on)
            except Exception as exc:
                last_exc = exc
                wait = _BACKOFF_BASE**attempt
                logger.warning(
                    "sidecar_token_retry",
                    attempt=attempt,
                    wait=wait,
                    error=str(exc),
                )
                if attempt < _MAX_RETRIES:
                    time.sleep(wait)

        raise RuntimeError(
            f"Failed to acquire token from sidecar after {_MAX_RETRIES} attempts"
        ) from last_exc

    # -- internals ----------------------------------------------------------

    def _fetch_token(self) -> tuple[str, int]:
        url = (
            f"{self._sidecar_url}"
            f"/AuthorizationHeaderUnauthenticated/{self._api_name}"
        )
        params = {"AgentIdentity": self._agent_identity}

        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()

        body = resp.json()
        auth_header: str = body.get("Authorization", "")
        if not auth_header.lower().startswith("bearer "):
            raise ValueError(
                "Sidecar response missing or malformed Authorization header"
            )
        token = auth_header.split(" ", 1)[1]
        expires_on = _decode_jwt_exp(token)
        return token, expires_on


def _decode_jwt_exp(token: str) -> int:
    """Best-effort JWT exp extraction; falls back to now + 1 hour."""
    try:
        payload_segment = token.split(".")[1]
        # Pad base64
        padded = payload_segment + "=" * (-len(payload_segment) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        return int(payload["exp"])
    except Exception:
        return int(time.time()) + 3600
