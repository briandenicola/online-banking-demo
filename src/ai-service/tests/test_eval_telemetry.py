"""Unit tests for app.telemetry — verifies structured-logging fields land on
simulated openai BadRequestError-style exceptions, and that the JWT decoder
extracts the claims used by identity_startup_probe.

Net-network paths are NOT exercised; we only verify the field-extraction
behavior used by the eval-path instrumentation added for #137 RCA.
"""
import base64
import json

import pytest

from app.telemetry import (
    decode_jwt_claims_unverified,
    extract_openai_error_fields,
    redact_authorization_header,
)


def _make_jwt(payload: dict) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"{header}.{body}.sig"


def test_decode_jwt_claims_extracts_known_fields():
    token = _make_jwt({
        "oid": "00000000-0000-0000-0000-000000000abc",
        "appid": "11111111-1111-1111-1111-111111111111",
        "aud": "https://cognitiveservices.azure.com",
        "iss": "https://sts.windows.net/tid/",
        "tid": "22222222-2222-2222-2222-222222222222",
        "exp": 9999999999,
        "extra": "should-be-dropped",
    })
    claims = decode_jwt_claims_unverified(token)
    assert claims["oid"] == "00000000-0000-0000-0000-000000000abc"
    assert claims["appid"] == "11111111-1111-1111-1111-111111111111"
    assert claims["aud"] == "https://cognitiveservices.azure.com"
    assert claims["tid"] == "22222222-2222-2222-2222-222222222222"
    assert "extra" not in claims


def test_redact_authorization_header_keeps_claims_drops_token():
    token = _make_jwt({"oid": "abc", "appid": "xyz", "aud": "https://x"})
    redacted = redact_authorization_header(f"Bearer {token}")
    assert redacted["scheme"] == "Bearer"
    assert redacted["token"] == "<redacted>"
    assert redacted["claims"]["oid"] == "abc"
    assert redacted["claims"]["appid"] == "xyz"
    # Token VALUE is not anywhere in the structure
    assert token not in json.dumps(redacted)


class _FakeResponse:
    def __init__(self, status, headers, text):
        self.status_code = status
        self.headers = headers
        self.text = text


class _FakeBadRequestError(Exception):
    """Mimic shape of openai.BadRequestError for the fields we read."""
    def __init__(self, message, status_code, body, response):
        super().__init__(message)
        self.status_code = status_code
        self.body = body
        self.response = response
        self.code = body.get("error", {}).get("code") if isinstance(body, dict) else None


def test_extract_openai_error_fields_captures_raisvc_403_envelope():
    # Exactly the envelope shape Brian saw on #137: 400 wrapping a raisvc 403.
    body = {
        "error": {
            "code": "BadRequest",
            "message": "Evaluation request rejected.",
            "componentName": "raisvc",
            "correlation": "corr-abc-123",
            "innerError": {
                "code": "UnauthorizedUserAction",
                "componentName": "raisvc",
                "correlation": "inner-corr-456",
            },
        }
    }
    response = _FakeResponse(
        status=400,
        headers={
            "x-ms-request-id": "req-xyz",
            "x-ms-correlation-request-id": "ms-corr-789",
            "apim-request-id": "apim-111",
            "content-type": "application/json",
        },
        text=json.dumps(body),
    )
    exc = _FakeBadRequestError("400 Bad Request", 400, body, response)

    fields = extract_openai_error_fields(exc)

    assert fields["error_type"] == "_FakeBadRequestError"
    assert fields["openai_status_code"] == 400
    assert fields["openai_code"] == "BadRequest"
    assert fields["openai_body"] == body
    assert fields["foundry_componentName"] == "raisvc"
    assert fields["foundry_correlation"] == "corr-abc-123"
    assert fields["foundry_inner_code"] == "UnauthorizedUserAction"
    assert fields["foundry_inner_componentName"] == "raisvc"
    assert fields["foundry_inner_correlation"] == "inner-corr-456"
    assert fields["http_status"] == 400
    assert fields["http_ms_headers"]["x-ms-request-id"] == "req-xyz"
    assert fields["http_ms_headers"]["apim-request-id"] == "apim-111"
    assert "BadRequest" in fields["http_body"]


def test_extract_openai_error_fields_handles_plain_exception():
    fields = extract_openai_error_fields(RuntimeError("boom"))
    assert fields["error_type"] == "RuntimeError"
    assert fields["error_message"] == "boom"
    # No openai/http fields when the exception lacks them
    assert "openai_status_code" not in fields
    assert "http_status" not in fields


def test_structlog_emits_diagnostic_fields_on_simulated_400(caplog):
    """Verify the wrap-and-log pattern used in run_foundry_evaluation lands the
    raisvc fields in the structlog output on a simulated BadRequestError.
    """
    import logging
    import structlog

    # Make structlog write through stdlib so caplog can see it.
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )
    log = structlog.get_logger("ai-service.test")

    body = {
        "error": {
            "code": "BadRequest",
            "componentName": "raisvc",
            "correlation": "corr-xyz",
            "innerError": {"code": "UnauthorizedUserAction", "componentName": "raisvc"},
        }
    }
    response = _FakeResponse(400,
                             {"x-ms-request-id": "abc", "apim-request-id": "def"},
                             json.dumps(body))
    exc = _FakeBadRequestError("bad", 400, body, response)

    diag = extract_openai_error_fields(exc)
    with caplog.at_level(logging.ERROR, logger="ai-service.test"):
        log.bind(component="run_foundry_evaluation", request_id="rid-1").error(
            "foundry.eval.invoke.failed", **diag,
        )

    rendered = "\n".join(r.getMessage() for r in caplog.records)
    assert "foundry.eval.invoke.failed" in rendered
    assert "raisvc" in rendered
    assert "UnauthorizedUserAction" in rendered
    assert "corr-xyz" in rendered
    assert "rid-1" in rendered
    assert "x-ms-request-id" in rendered
    assert "apim-request-id" in rendered
