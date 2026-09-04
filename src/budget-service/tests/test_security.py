"""
Security tests for budget-service JWT authentication (Issue #26).

These tests verify that:
- Endpoints reject requests without a valid JWT
- Endpoints reject requests with invalid/expired JWTs
- Health endpoints remain accessible without auth
- User identity from JWT is used (not from URL path)
"""

import time
import pytest
from fastapi.testclient import TestClient

import jwt as pyjwt

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

SERVICE_NAME = "budget-service"
JWT_ISSUER = issuer_name()
JWT_AUDIENCE = audience_for(SERVICE_NAME)


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


def _expired_token() -> str:
    """Create an expired JWT."""
    return _make_token(expires_in=-3600)


def _wrong_secret_token() -> str:
    """Create a JWT signed with the wrong secret."""
    return _make_token(secret=foreign_private_key_pem())


def _wrong_issuer_token() -> str:
    """Create a JWT with wrong issuer."""
    return _make_token(issuer="evil-service")


def _admin_token() -> str:
    """Create a JWT with admin role."""
    return _make_token(user_id="usr-admin-001", role="Admin")


@pytest.fixture
def client():
    """Create a test client with JWT_KEY configured."""
    import os
    _configure_auth_env()
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


# =====================================================================
# Health endpoints — must work WITHOUT auth
# =====================================================================

class TestHealthEndpointsNoAuth:
    """SECURITY: Health/readiness endpoints must be accessible without auth."""

    def test_health_no_auth(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_healthz_no_auth(self, client):
        resp = client.get("/healthz")
        assert resp.status_code == 200

    def test_readyz_no_auth(self, client):
        resp = client.get("/readyz")
        assert resp.status_code == 200


# =====================================================================
# Protected endpoints — must REJECT without valid JWT
# =====================================================================

class TestInsightsEndpointAuth:
    """SECURITY: /insights/{userId} must require valid JWT."""

    def test_no_token_returns_401(self, client):
        """Requests without Authorization header must be rejected."""
        resp = client.get("/insights/usr-test-001")
        assert resp.status_code in (401, 403)

    def test_invalid_token_returns_401(self, client):
        """Requests with malformed token must be rejected."""
        resp = client.get(
            "/insights/usr-test-001",
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        assert resp.status_code == 401

    def test_expired_token_returns_401(self, client):
        """Requests with expired JWT must be rejected."""
        resp = client.get(
            "/insights/usr-test-001",
            headers={"Authorization": f"Bearer {_expired_token()}"},
        )
        assert resp.status_code == 401

    def test_wrong_secret_returns_401(self, client):
        """Requests with JWT signed by wrong key must be rejected."""
        resp = client.get(
            "/insights/usr-test-001",
            headers={"Authorization": f"Bearer {_wrong_secret_token()}"},
        )
        assert resp.status_code == 401

    def test_wrong_issuer_returns_401(self, client):
        """Requests with wrong issuer must be rejected."""
        resp = client.get(
            "/insights/usr-test-001",
            headers={"Authorization": f"Bearer {_wrong_issuer_token()}"},
        )
        assert resp.status_code == 401

    def test_valid_token_succeeds(self, client):
        """Requests with valid JWT should succeed (200)."""
        token = _make_token()
        resp = client.get(
            "/insights/usr-test-001",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

    def test_path_userid_ignored_jwt_identity_used(self, client):
        """
        SECURITY: The userId in the path must be overridden by the JWT identity.
        Even if the path says 'other-user', the service must use the JWT's userId.
        """
        token = _make_token(user_id="usr-test-001")
        resp = client.get(
            "/insights/other-user-id",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["userId"] == "usr-test-001"


class TestCategorizeEndpointAuth:
    """SECURITY: /categorize must require valid JWT."""

    def test_no_token_returns_401(self, client):
        resp = client.post("/categorize", params={"description": "coffee shop"})
        assert resp.status_code in (401, 403)

    def test_expired_token_returns_401(self, client):
        resp = client.post(
            "/categorize",
            params={"description": "coffee shop"},
            headers={"Authorization": f"Bearer {_expired_token()}"},
        )
        assert resp.status_code == 401

    def test_valid_token_succeeds(self, client):
        token = _make_token()
        resp = client.post(
            "/categorize",
            params={"description": "coffee shop"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
