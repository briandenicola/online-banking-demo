import pytest
from fastapi import Request
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client for the budget service."""
    from app.main import app
    from app.auth import UserContext, verify_jwt

    def _override_user(request: Request) -> UserContext:
        user_id = request.path_params.get("userId", "test-user")
        return UserContext(user_id=user_id, username="testuser", role="User")

    app.dependency_overrides[verify_jwt] = _override_user
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
