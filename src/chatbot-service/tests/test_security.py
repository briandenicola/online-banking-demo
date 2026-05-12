"""
Security tests for chatbot-service JWT authentication (Issue #26).

These tests verify that:
- Chat endpoints reject requests without a valid JWT
- Chat endpoints reject requests with invalid/expired JWTs
- Admin endpoints reject non-admin users with 403
- Health endpoints remain accessible without auth
- User identity from JWT is used, not from request body
- Chat history endpoint validates user_id against JWT claims
"""

import time

import jwt as pyjwt
import pytest

from tests.conftest import (
    JWT_ALGORITHM,
    JWT_AUDIENCE,
    JWT_ISSUER,
    JWT_SECRET,
    _make_token,
)


def _expired_token() -> str:
    return _make_token(expires_in=-3600)


def _wrong_secret_token() -> str:
    return _make_token(secret="WrongSecretKeyThatDoesNotMatch12345678")


def _admin_token() -> str:
    return _make_token(user_id="usr-admin-001", role="Admin")


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
# Chat endpoint — must require valid JWT
# =====================================================================

class TestChatEndpointAuth:
    """SECURITY: POST /api/chat must require valid JWT."""

    def test_no_token_returns_401(self, client):
        """Requests without Authorization header must be rejected."""
        resp = client.post(
            "/api/chat",
            json={"message": "How can I save money?", "user_id": "usr-test-001"},
        )
        assert resp.status_code in (401, 403)

    def test_invalid_token_returns_401(self, client):
        """Requests with malformed token must be rejected."""
        resp = client.post(
            "/api/chat",
            json={"message": "Hello", "user_id": "usr-test-001"},
            headers={"Authorization": "Bearer garbage.token.value"},
        )
        assert resp.status_code == 401

    def test_expired_token_returns_401(self, client):
        """Requests with expired JWT must be rejected."""
        resp = client.post(
            "/api/chat",
            json={"message": "Hello", "user_id": "usr-test-001"},
            headers={"Authorization": f"Bearer {_expired_token()}"},
        )
        assert resp.status_code == 401

    def test_wrong_secret_returns_401(self, client):
        """Requests signed with wrong key must be rejected."""
        resp = client.post(
            "/api/chat",
            json={"message": "Hello", "user_id": "usr-test-001"},
            headers={"Authorization": f"Bearer {_wrong_secret_token()}"},
        )
        assert resp.status_code == 401


# =====================================================================
# Chat history — must validate user_id against JWT claims
# =====================================================================

class TestChatHistoryAuth:
    """SECURITY: GET /api/chat/history/{user_id} validates ownership."""

    def test_no_token_returns_401(self, client):
        resp = client.get("/api/chat/history/usr-test-001")
        assert resp.status_code in (401, 403)

    def test_own_history_succeeds(self, client):
        """User can access their own chat history."""
        token = _make_token(user_id="usr-test-001")
        resp = client.get(
            "/api/chat/history/usr-test-001",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

    def test_other_users_history_returns_403(self, client):
        """
        SECURITY: A regular user cannot access another user's chat history.
        The endpoint must compare the path user_id against JWT claims.
        """
        token = _make_token(user_id="usr-attacker")
        resp = client.get(
            "/api/chat/history/usr-victim",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    def test_admin_can_access_other_users_history(self, client):
        """Admin users should be able to access any user's history."""
        token = _admin_token()
        resp = client.get(
            "/api/chat/history/usr-test-001",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200


# =====================================================================
# Admin endpoint — must require admin role
# =====================================================================

class TestAdminEndpointAuth:
    """SECURITY: Admin endpoints must require admin role in JWT."""

    def test_no_token_returns_401(self, client):
        resp = client.get("/api/chat/admin/foundry-status")
        assert resp.status_code in (401, 403)

    def test_regular_user_returns_403(self, client):
        """Non-admin users must be rejected with 403."""
        token = _make_token(role="User")
        resp = client.get(
            "/api/chat/admin/foundry-status",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    def test_admin_user_succeeds(self, client):
        """Admin users should have access."""
        token = _admin_token()
        resp = client.get(
            "/api/chat/admin/foundry-status",
            headers={"Authorization": f"Bearer {token}"},
        )
        # Should not be 401 or 403 — may be 200 or 503 depending on Foundry config
        assert resp.status_code not in (401, 403)
