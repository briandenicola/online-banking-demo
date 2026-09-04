import sys as _sys
from pathlib import Path as _Path

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

# --- #334: the RS256 test key and the canonical audiences live in tests/security/ ---
for _parent in _Path(__file__).resolve().parents:
    _helpers = _parent / "tests" / "security"
    if (_helpers / "jwt_test_keys.py").is_file():
        if str(_helpers) not in _sys.path:
            _sys.path.insert(0, str(_helpers))
        break
else:  # pragma: no cover - the helper is committed; its absence is a broken checkout
    raise RuntimeError("tests/security/jwt_test_keys.py not found")

from jwt_test_keys import audience_for, issuer_name, public_key_pem  # noqa: E402


@pytest.fixture(autouse=True)
def _auth_environment(monkeypatch):
    """Every test gets the validating half of the key and this service's own audience.

    Autouse because the service now refuses to start without them — which is the intended
    behaviour, and a test suite that quietly ran without auth configured would be testing a
    deployment shape that no longer exists.
    """
    for retired in ("JWT_KEY", "JWT_SECRET", "JWT_PRIVATE_KEY_PEM"):
        monkeypatch.delenv(retired, raising=False)
    monkeypatch.setenv("JWT_PUBLIC_KEY_PEM", public_key_pem())
    monkeypatch.setenv("JWT_ISSUER", issuer_name())
    monkeypatch.setenv("JWT_AUDIENCE", audience_for("budget-service"))

    from app.auth import reset_key_cache

    reset_key_cache()


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
