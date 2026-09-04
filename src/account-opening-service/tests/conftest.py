"""Shared fixtures for account-opening-service tests."""
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import sys as _sys
from pathlib import Path as _Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# --- #334: the RS256 test key and the canonical audiences live in tests/security/ ---
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
    mediator_audience,
    public_key_pem,
)

SERVICE_NAME = "account-opening-service"
JWT_ISSUER = issuer_name()
JWT_AUDIENCE = audience_for(SERVICE_NAME)


@pytest.fixture(autouse=True)
def _auth_environment(monkeypatch):
    """Hand the service the validating half of the key and nothing else.

    Autouse because after #334 the service refuses to start without it, and a suite that
    quietly ran with auth unconfigured would be exercising a deployment shape that no
    longer exists.
    """
    for retired in ("JWT_KEY", "JWT_SECRET", "JWT_PRIVATE_KEY_PEM"):
        monkeypatch.delenv(retired, raising=False)
    monkeypatch.setenv("JWT_PUBLIC_KEY_PEM", public_key_pem())
    monkeypatch.setenv("JWT_ISSUER", JWT_ISSUER)
    monkeypatch.setenv("JWT_AUDIENCE", JWT_AUDIENCE)
    monkeypatch.setenv("JWT_ADDITIONAL_AUDIENCES", mediator_audience())

    from app.auth import reset_key_cache

    reset_key_cache()


def _make_token(
    user_id: str = "usr-test-001",
    email: str = "testuser@banking-demo.com",
    role: str = "User",
    expires_minutes: int = 60,
    audience=None,
    signing_key=None,
) -> str:
    """Create a signed JWT matching user-service format."""
    return make_token(
        user_id=user_id,
        role=role,
        audience=audience if audience is not None else JWT_AUDIENCE,
        issuer=JWT_ISSUER,
        expires_in=expires_minutes * 60,
        signing_key=signing_key,
        extra_claims={"email": email, "jti": str(uuid.uuid4())},
    )


@pytest.fixture
def auth_token() -> str:
    """Valid JWT for a regular User."""
    return _make_token(role="User")


@pytest.fixture
def admin_token() -> str:
    """Valid JWT for an Admin user."""
    return _make_token(
        user_id="usr-admin-001",
        email="admin@banking-demo.com",
        role="Admin",
    )


@pytest.fixture
def sample_application() -> dict:
    """Valid application form data matching the spec schema."""
    return {
        "firstName": "John",
        "lastName": "Doe",
        "dateOfBirth": "1990-01-15",
        "address": "123 Main St, Springfield, IL 62704",
        "email": "john.doe@example.com",
        "phone": "+12025551234",
        "ssn": "6789",
        "employment": "Software Engineer",
        "annualIncome": 95000,
        "accountType": "checking",
    }


@pytest.fixture
def mock_redis():
    """Mock Redis client for event publishing tests."""
    mock = AsyncMock()
    mock.xadd = AsyncMock(return_value=b"1234567890-0")
    mock.xgroup_create = AsyncMock(return_value=True)
    mock.xreadgroup = AsyncMock(return_value=[])
    mock.xack = AsyncMock(return_value=1)
    mock.close = AsyncMock()
    return mock


@pytest_asyncio.fixture
async def app_client(mock_redis):
    """httpx.AsyncClient wired to the FastAPI app (no real server)."""
    from app.main import app
    from app.dependencies import (
        get_blob_service_client,
        get_redis_client,
        get_repository,
        get_state_machine,
    )
    from app.repository import InMemoryApplicationRepository
    from app.state_machine import ApplicationStateMachine

    repository = InMemoryApplicationRepository()
    state_machine = ApplicationStateMachine()
    
    async def override_repository():
        return repository
    
    async def override_redis():
        return mock_redis
    
    async def override_blob_client():
        return None
    
    async def override_state_machine():
        return state_machine
    
    app.dependency_overrides[get_repository] = override_repository
    app.dependency_overrides[get_redis_client] = override_redis
    app.dependency_overrides[get_blob_service_client] = override_blob_client
    app.dependency_overrides[get_state_machine] = override_state_machine

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
