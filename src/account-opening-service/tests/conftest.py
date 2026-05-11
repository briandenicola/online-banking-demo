"""Shared fixtures for account-opening-service tests."""
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from jose import jwt

# JWT settings matching user-service appsettings.json
JWT_SECRET = os.getenv(
    "JWT_SECRET", "YourSuperSecretKeyForJWTTokenGeneration12345"
)
JWT_ALGORITHM = "HS256"
JWT_ISSUER = "user-service"
JWT_AUDIENCE = "banking-demo"


def _make_token(
    user_id: str = "usr-test-001",
    email: str = "testuser@banking-demo.com",
    role: str = "User",
    expires_minutes: int = 60,
) -> str:
    """Create a signed JWT matching user-service format."""
    now = datetime.now(timezone.utc)
    claims = {
        "sub": user_id,
        "email": email,
        "role": role,
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=expires_minutes)).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(claims, JWT_SECRET, algorithm=JWT_ALGORITHM)


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
async def app_client():
    """httpx.AsyncClient wired to the FastAPI app (no real server)."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
