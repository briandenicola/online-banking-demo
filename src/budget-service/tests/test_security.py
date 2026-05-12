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

# JWT config matching user-service defaults
JWT_SECRET = "YourSuperSecretKeyForJWTTokenGeneration12345"
JWT_ALGORITHM = "HS256"
JWT_ISSUER = "user-service"
JWT_AUDIENCE = "banking-demo"


def _make_token(
    user_id: str = "usr-test-001",
    role: str = "User",
    expires_in: int = 3600,
    issuer: str = JWT_ISSUER,
    audience: str = JWT_AUDIENCE,
    secret: str = JWT_SECRET,
) -> str:
    """Create a signed JWT matching user-service format."""
    now = int(time.time())
    claims = {
        "sub": user_id,
        "userId": user_id,
        "unique_name": "testuser",
        "role": role,
        "iss": issuer,
        "aud": audience,
        "iat": now,
        "exp": now + expires_in,
        "jti": "test-jti-001",
    }
    return pyjwt.encode(claims, secret, algorithm=JWT_ALGORITHM)


def _expired_token() -> str:
    """Create an expired JWT."""
    return _make_token(expires_in=-3600)


def _wrong_secret_token() -> str:
    """Create a JWT signed with the wrong secret."""
    return _make_token(secret="WrongSecretKeyThatDoesNotMatch12345678")


def _wrong_issuer_token() -> str:
    """Create a JWT with wrong issuer."""
    return _make_token(issuer="evil-service")


def _admin_token() -> str:
    """Create a JWT with admin role."""
    return _make_token(user_id="usr-admin-001", role="Admin")


@pytest.fixture
def client():
    """Create a test client with Jwt__Key configured."""
    import os
    os.environ["Jwt__Key"] = JWT_SECRET
    os.environ["Jwt__Issuer"] = JWT_ISSUER
    os.environ["Jwt__Audience"] = JWT_AUDIENCE
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
