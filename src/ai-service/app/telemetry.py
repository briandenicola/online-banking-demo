"""
Structured telemetry helpers for the ai-service Foundry / eval path.

Adds visibility (NOT diagnosis) around the Azure AI Foundry calls so that
when the next eval invocation fires we capture EVERYTHING needed to confirm
or refute root-cause hypotheses on the first try (per directive
copilot-directive-20260514T020930Z-observability-bias.md).

Components:
  * decode_jwt_claims_unverified — base64-decode JWT body, return dict; never
    used for auth decisions, ONLY for structured logging.
  * redact_authorization_header — replaces the bearer token VALUE while
    preserving the decoded JWT claims (oid/appid/aud/iss/tid).
  * identity_startup_probe — one-shot async probe that acquires a token for
    cognitiveservices.azure.com, decodes the JWT, and emits a structured
    log line. Failure is non-fatal.
  * foundry_http_debug — async context manager that monkey-patches
    httpx.AsyncClient.send for the lifetime of the block to log every
    request/response made by the openai/agent_framework_foundry SDK. Guarded
    by env AI_SERVICE_DEBUG_FOUNDRY=1.

Why monkey-patch instead of httpx event_hooks: agent_framework_foundry
constructs its own AsyncOpenAI client internally; we cannot inject hooks
without touching SDK code. Patching httpx.AsyncClient.send for the duration
of a single evaluate() call is contained, reversible, and captures the wire
traffic we need without changing any SDK behavior.
"""
from __future__ import annotations

import base64
import contextlib
import json
import os
from typing import Any, Optional

import httpx
import structlog

logger = structlog.get_logger("ai-service.telemetry")

DEBUG_ENV_VAR = "AI_SERVICE_DEBUG_FOUNDRY"
_MAX_BODY_LOG = 4096


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def decode_jwt_claims_unverified(token: str) -> dict:
    """Return the JWT payload as a dict. NO signature verification — logging only."""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload = json.loads(_b64url_decode(parts[1]).decode("utf-8"))
        return {
            k: payload.get(k)
            for k in ("oid", "appid", "aud", "iss", "tid", "exp", "sub", "upn", "azp")
            if k in payload
        }
    except Exception as e:  # noqa: BLE001
        return {"_decode_error": str(e)}


def redact_authorization_header(value: str) -> dict:
    """Return a redacted representation that keeps JWT claims but hides the token."""
    if not value:
        return {"present": False}
    parts = value.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        claims = decode_jwt_claims_unverified(parts[1])
        return {"scheme": "Bearer", "token": "<redacted>", "claims": claims}
    return {"scheme": parts[0] if parts else "?", "token": "<redacted>"}


def _redact_headers(headers) -> dict:
    out = {}
    for k, v in headers.items():
        lk = k.lower()
        if lk == "authorization":
            out[k] = redact_authorization_header(v)
        elif lk in ("api-key", "x-api-key", "ocp-apim-subscription-key"):
            out[k] = "<redacted>"
        else:
            out[k] = v
    return out


def _truncate(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    if len(text) <= _MAX_BODY_LOG:
        return text
    return text[:_MAX_BODY_LOG] + f"...<truncated {len(text) - _MAX_BODY_LOG} bytes>"


def debug_enabled() -> bool:
    return os.getenv(DEBUG_ENV_VAR, "0") == "1"


async def identity_startup_probe(credential: Any, foundry_endpoint: Optional[str]) -> None:
    """One-shot startup probe: acquire token for cognitiveservices.azure.com,
    log decoded JWT claims and the resolved Foundry endpoint. Never raises.
    """
    scope = "https://cognitiveservices.azure.com/.default"
    log = logger.bind(component="identity_startup_probe", scope=scope)
    try:
        import asyncio
        token = await asyncio.to_thread(credential.get_token, scope)
        claims = decode_jwt_claims_unverified(token.token)
        # Best-effort derivation of AI Services account name from endpoint host.
        target_resource = None
        if foundry_endpoint:
            try:
                from urllib.parse import urlparse
                host = urlparse(foundry_endpoint).hostname or ""
                target_resource = host
            except Exception:  # noqa: BLE001
                target_resource = foundry_endpoint
        log.info(
            "foundry.identity.probe.ok",
            foundry_endpoint=foundry_endpoint,
            target_resource_host=target_resource,
            token_expires_on=token.expires_on,
            principal_oid=claims.get("oid"),
            principal_appid=claims.get("appid"),
            token_aud=claims.get("aud"),
            token_iss=claims.get("iss"),
            token_tid=claims.get("tid"),
            token_exp=claims.get("exp"),
            debug_hook_enabled=debug_enabled(),
        )
    except Exception as e:  # noqa: BLE001
        log.warning(
            "foundry.identity.probe.failed",
            error=str(e),
            error_type=type(e).__name__,
            foundry_endpoint=foundry_endpoint,
        )


@contextlib.asynccontextmanager
async def foundry_http_debug(request_id: str):
    """Monkey-patch httpx.AsyncClient.send for the lifetime of the block.

    Logs full request line, redacted headers (with decoded JWT claims),
    request body summary, response status, response headers (especially
    x-ms-* / apim-request-id / correlation-id), and response body
    (truncated to 4KB). Reverts the patch on exit.

    Disabled (no-op) unless AI_SERVICE_DEBUG_FOUNDRY=1.
    """
    if not debug_enabled():
        yield
        return

    original_send = httpx.AsyncClient.send

    async def patched_send(self, request, **kwargs):
        bound = logger.bind(
            component="foundry_http_debug",
            request_id=request_id,
            http_method=request.method,
            http_url=str(request.url),
        )
        try:
            req_body_text = None
            try:
                if request.content:
                    req_body_text = _truncate(request.content.decode("utf-8", errors="replace"))
            except Exception:  # noqa: BLE001
                req_body_text = "<unreadable>"
            bound.info(
                "foundry.http.request",
                headers=_redact_headers(request.headers),
                body=req_body_text,
            )
        except Exception as e:  # noqa: BLE001
            bound.warning("foundry.http.request.log_failed", error=str(e))

        try:
            response = await original_send(self, request, **kwargs)
        except Exception as e:  # noqa: BLE001
            bound.error(
                "foundry.http.transport_error",
                error=str(e),
                error_type=type(e).__name__,
            )
            raise

        try:
            resp_text = None
            try:
                # response.read() is needed to materialize body for streaming responses
                await response.aread()
                resp_text = _truncate(response.text)
            except Exception:  # noqa: BLE001
                resp_text = "<unreadable>"
            ms_headers = {k: v for k, v in response.headers.items()
                          if k.lower().startswith("x-ms-")
                          or k.lower() in ("apim-request-id", "correlation-id",
                                           "x-request-id", "request-id",
                                           "x-correlation-request-id")}
            bound.info(
                "foundry.http.response",
                status_code=response.status_code,
                ms_headers=ms_headers,
                all_headers=dict(response.headers),
                body=resp_text,
            )
        except Exception as e:  # noqa: BLE001
            bound.warning("foundry.http.response.log_failed", error=str(e))

        return response

    httpx.AsyncClient.send = patched_send  # type: ignore[assignment]
    try:
        yield
    finally:
        httpx.AsyncClient.send = original_send  # type: ignore[assignment]


def extract_openai_error_fields(exc: BaseException) -> dict:
    """Pull every diagnostic field we care about from an openai/httpx exception."""
    fields: dict = {
        "error_type": type(exc).__name__,
        "error_message": str(exc),
    }
    # openai BadRequestError / APIStatusError style
    for attr in ("status_code", "code", "type", "param", "request_id"):
        v = getattr(exc, attr, None)
        if v is not None:
            fields[f"openai_{attr}"] = v
    body = getattr(exc, "body", None)
    if body is not None:
        try:
            fields["openai_body"] = body if isinstance(body, (dict, list)) else str(body)
            # Walk nested innerError / componentName / correlation
            if isinstance(body, dict):
                err = body.get("error", body)
                for k in ("componentName", "correlation", "innerError",
                          "code", "message"):
                    if isinstance(err, dict) and k in err:
                        fields[f"foundry_{k}"] = err[k]
                inner = err.get("innerError") if isinstance(err, dict) else None
                if isinstance(inner, dict):
                    for k in ("code", "componentName", "correlation"):
                        if k in inner:
                            fields[f"foundry_inner_{k}"] = inner[k]
        except Exception:  # noqa: BLE001
            pass
    # httpx response on the exception
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            fields["http_status"] = getattr(response, "status_code", None)
            headers = getattr(response, "headers", {}) or {}
            try:
                fields["http_headers"] = _redact_headers(headers)
                fields["http_ms_headers"] = {
                    k: v for k, v in headers.items()
                    if k.lower().startswith("x-ms-")
                    or k.lower() in ("apim-request-id", "correlation-id",
                                     "x-request-id", "request-id")
                }
            except Exception:  # noqa: BLE001
                pass
            try:
                text = response.text
                fields["http_body"] = _truncate(text)
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            pass
    return fields
