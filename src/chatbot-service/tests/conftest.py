"""Shared fixtures for chatbot-service security tests."""

import os
import time
from contextlib import asynccontextmanager

import pytest
import jwt as pyjwt
from fastapi.testclient import TestClient

# --- #334: token helpers live in tests/security/ so audiences are stated once ---
import sys as _sys
from pathlib import Path as _Path

for _parent in _Path(__file__).resolve().parents:
    _helpers = _parent / "tests" / "security"
    if (_helpers / "jwt_test_keys.py").is_file():
        if str(_helpers) not in _sys.path:
            _sys.path.insert(0, str(_helpers))
        break
else:  # pragma: no cover - the helper is committed; its absence is a broken checkout
    raise RuntimeError("tests/security/jwt_test_keys.py not found")

from jwt_test_keys import (  # noqa: E402
    audience_for,
    foreign_private_key_pem,
    issuer_name,
    make_token,
    public_key_pem,
)

SERVICE_NAME = "chatbot-service"
JWT_ISSUER = issuer_name()
JWT_AUDIENCE = audience_for(SERVICE_NAME)


@pytest.fixture(autouse=True)
def _auth_environment(monkeypatch):
    """Give the service the validating half of the key and its own audience.

    Autouse because the service now refuses to start without them, and a suite that quietly
    ran with auth unconfigured would be exercising a deployment shape that no longer exists.
    """
    for retired in ("JWT_KEY", "JWT_SECRET", "JWT_PRIVATE_KEY_PEM"):
        monkeypatch.delenv(retired, raising=False)
    monkeypatch.setenv("JWT_PUBLIC_KEY_PEM", public_key_pem())
    monkeypatch.setenv("JWT_ISSUER", JWT_ISSUER)
    monkeypatch.setenv("JWT_AUDIENCE", JWT_AUDIENCE)

    from app.auth import reset_key_cache

    reset_key_cache()


def _make_token(
    user_id: str = "usr-test-001",
    role: str = "User",
    expires_in: int = 3600,
    issuer: str = None,
    audience=None,
    secret: str = None,
) -> str:
    """Mint a token this service should accept.

    ``secret`` is retained so existing negative tests keep reading naturally, but it now
    means "sign with this key instead of the issuer's" — under RS256 a wrong key is a
    different keypair, not a different string.
    """
    return make_token(
        user_id=user_id,
        role=role,
        expires_in=expires_in,
        issuer=issuer if issuer is not None else JWT_ISSUER,
        audience=audience if audience is not None else JWT_AUDIENCE,
        signing_key=secret,
    )


def _configure_auth_env() -> None:
    """Give the service the validating half only. It could not mint if it wanted to."""
    import os as _os

    for _retired in ("JWT_KEY", "JWT_SECRET", "JWT_PRIVATE_KEY_PEM"):
        _os.environ.pop(_retired, None)
    _os.environ["JWT_PUBLIC_KEY_PEM"] = public_key_pem()
    _os.environ["JWT_ISSUER"] = JWT_ISSUER
    _os.environ["JWT_AUDIENCE"] = JWT_AUDIENCE

    from app.auth import reset_key_cache

    reset_key_cache()


@pytest.fixture
def client():
    """Create a test client with JWT_KEY configured."""
    _configure_auth_env()
    from app.main import app
    from app.services.agent_service import AgentState, get_agent_state

    @asynccontextmanager
    async def _no_lifespan(_: object):
        yield

    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = _no_lifespan
    app.dependency_overrides[get_agent_state] = lambda: AgentState()
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    app.router.lifespan_context = original_lifespan
