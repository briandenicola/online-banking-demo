"""
Security tests for ai-service JWT authentication (Issue #26).

These tests verify that:
- The /detect endpoint requires a valid JWT
- All /api/admin/* endpoints require admin role
- Non-admin users get 403 on admin endpoints
- Health endpoints remain accessible without auth
- Invalid/expired JWTs are rejected
"""

import time
import os
from contextlib import asynccontextmanager

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

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
    return _make_token(expires_in=-3600)


def _wrong_secret_token() -> str:
    return _make_token(secret="WrongSecretKeyThatDoesNotMatch12345678")


def _admin_token() -> str:
    return _make_token(user_id="usr-admin-001", role="Admin")


@pytest.fixture
def client():
    """Create a test client with JWT_KEY configured."""
    os.environ["JWT_KEY"] = JWT_SECRET
    os.environ["JWT_ISSUER"] = JWT_ISSUER
    os.environ["JWT_AUDIENCE"] = JWT_AUDIENCE
    from app.main import app
    from app.services.anomaly_service import AnomalyState, get_anomaly_state

    @asynccontextmanager
    async def _no_lifespan(_: object):
        yield

    state = AnomalyState()
    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = _no_lifespan
    app.dependency_overrides[get_anomaly_state] = lambda: state
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    app.router.lifespan_context = original_lifespan


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
# /detect endpoint — requires valid JWT (any role)
# =====================================================================

class TestDetectEndpointAuth:
    """SECURITY: POST /detect must require valid JWT."""

    def test_no_token_returns_401(self, client):
        """Requests without Authorization header must be rejected."""
        resp = client.post(
            "/detect",
            json={
                "transactionId": "txn-001",
                "accountId": "acc-001",
                "amount": 100.0,
                "type": "Purchase",
                "description": "Coffee",
            },
        )
        assert resp.status_code in (401, 403)

    def test_invalid_token_returns_401(self, client):
        resp = client.post(
            "/detect",
            json={"transactionId": "txn-001", "amount": 100.0},
            headers={"Authorization": "Bearer invalid.token"},
        )
        assert resp.status_code == 401

    def test_expired_token_returns_401(self, client):
        resp = client.post(
            "/detect",
            json={"transactionId": "txn-001", "amount": 100.0},
            headers={"Authorization": f"Bearer {_expired_token()}"},
        )
        assert resp.status_code == 401

    def test_wrong_secret_returns_401(self, client):
        resp = client.post(
            "/detect",
            json={"transactionId": "txn-001", "amount": 100.0},
            headers={"Authorization": f"Bearer {_wrong_secret_token()}"},
        )
        assert resp.status_code == 401


# =====================================================================
# Admin endpoints — must require admin role
# =====================================================================

ADMIN_ENDPOINTS = [
    ("GET", "/api/admin/foundry-status"),
    ("GET", "/api/admin/stats"),
    ("GET", "/api/admin/transactions"),
    ("GET", "/api/admin/flagged-transactions"),
    ("GET", "/api/admin/prompts"),
]


class TestAdminEndpointsAuth:
    """SECURITY: All /api/admin/* endpoints must require admin role."""

    @pytest.mark.parametrize("method,path", ADMIN_ENDPOINTS)
    def test_no_token_returns_401(self, client, method, path):
        """Admin endpoints must reject unauthenticated requests."""
        resp = client.request(method, path)
        assert resp.status_code in (401, 403), (
            f"{method} {path} returned {resp.status_code} without auth"
        )

    @pytest.mark.parametrize("method,path", ADMIN_ENDPOINTS)
    def test_regular_user_returns_403(self, client, method, path):
        """Non-admin users must be rejected with 403 Forbidden."""
        token = _make_token(role="User")
        resp = client.request(
            method,
            path,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403, (
            f"{method} {path} returned {resp.status_code} for non-admin user"
        )

    @pytest.mark.parametrize("method,path", ADMIN_ENDPOINTS)
    def test_admin_user_not_rejected(self, client, method, path):
        """Admin users must not get auth errors (may get 503 if Redis unavailable)."""
        token = _admin_token()
        resp = client.request(
            method,
            path,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code not in (401, 403), (
            f"{method} {path} returned {resp.status_code} for admin user"
        )

    def test_evaluate_endpoint_no_auth_returns_401(self, client):
        """POST /api/admin/evaluate must require auth."""
        resp = client.post(
            "/api/admin/evaluate",
            json={"datasetUri": "test", "evaluators": ["relevance"]},
        )
        assert resp.status_code in (401, 403)

    def test_evaluate_endpoint_regular_user_returns_403(self, client):
        """POST /api/admin/evaluate must require admin role."""
        token = _make_token(role="User")
        resp = client.post(
            "/api/admin/evaluate",
            json={"datasetUri": "test", "evaluators": ["relevance"]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    def test_review_endpoint_no_auth_returns_401(self, client):
        """PUT /api/admin/flagged-transactions/{id}/review must require auth."""
        resp = client.put(
            "/api/admin/flagged-transactions/txn-001/review",
            json={"status": "reviewed", "reviewNotes": "test"},
        )
        assert resp.status_code in (401, 403)

    def test_review_endpoint_regular_user_returns_403(self, client):
        """PUT /api/admin/flagged-transactions/{id}/review must require admin."""
        token = _make_token(role="User")
        resp = client.put(
            "/api/admin/flagged-transactions/txn-001/review",
            json={"status": "reviewed", "reviewNotes": "test"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    def test_rescore_endpoint_no_auth_returns_401(self, client):
        """POST /api/admin/scored-transactions/{id}/rescore must require auth."""
        resp = client.post("/api/admin/scored-transactions/txn-001/rescore")
        assert resp.status_code in (401, 403)

    def test_rescore_endpoint_regular_user_returns_403(self, client):
        """POST /api/admin/scored-transactions/{id}/rescore must require admin."""
        token = _make_token(role="User")
        resp = client.post(
            "/api/admin/scored-transactions/txn-001/rescore",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403
