"""Shared fixtures for chatbot-service security tests."""

import os
import time
from contextlib import asynccontextmanager

import pytest
import jwt as pyjwt
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


@pytest.fixture
def client():
    """Create a test client with JWT_KEY configured."""
    os.environ["JWT_KEY"] = JWT_SECRET
    os.environ["JWT_ISSUER"] = JWT_ISSUER
    os.environ["JWT_AUDIENCE"] = JWT_AUDIENCE
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
