import sys as _sys
from pathlib import Path as _Path

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import asynccontextmanager
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

SERVICE_NAME = "ai-service"


@pytest.fixture(autouse=True)
def _auth_environment(monkeypatch):
    """Give the service the validating half of the key and its own audience.

    Autouse because the service now refuses to start without them, and a suite that quietly
    ran with auth unconfigured would be exercising a deployment shape that no longer exists.
    """
    for retired in ("JWT_KEY", "JWT_SECRET", "JWT_PRIVATE_KEY_PEM"):
        monkeypatch.delenv(retired, raising=False)
    monkeypatch.setenv("JWT_PUBLIC_KEY_PEM", public_key_pem())
    monkeypatch.setenv("JWT_ISSUER", issuer_name())
    monkeypatch.setenv("JWT_AUDIENCE", audience_for(SERVICE_NAME))

    from app.auth import reset_key_cache

    reset_key_cache()

from app.models import RiskAssessment
from app.services.anomaly_service import AnalyzerPipeline, AnomalyState, BaseAnalyzer, get_anomaly_state


@pytest.fixture
def client():
    """Create a test client for the anomaly service (no lifespan — no Redis/Foundry)."""
    from app.main import app

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


@pytest.fixture
def client_with_auth():
    """Create a test client with auth bypassed for pipeline-only behavior."""
    from app.main import app
    from app.auth import UserContext, verify_jwt

    @asynccontextmanager
    async def _no_lifespan(_: object):
        yield

    state = AnomalyState()
    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = _no_lifespan
    app.dependency_overrides[get_anomaly_state] = lambda: state
    app.dependency_overrides[verify_jwt] = lambda: UserContext(
        user_id="usr-test-001",
        username="testuser",
        role="User",
    )
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    app.router.lifespan_context = original_lifespan


@pytest.fixture
def sample_transaction():
    return {
        "transactionId": "txn-001",
        "accountId": "acc-001",
        "amount": 50.0,
        "type": "Purchase",
        "description": "Coffee shop",
        "category": "Food & Dining",
    }


@pytest.fixture
def high_risk_transaction():
    return {
        "transactionId": "txn-002",
        "accountId": "acc-002",
        "amount": 15000.0,
        "type": "Wire",
        "description": "International wire to unknown account",
        "category": "Transfer",
    }


@pytest.fixture
def mock_pipeline():
    """Create a mock analyzer pipeline for testing."""
    pipeline = AnalyzerPipeline()
    return pipeline


class FakeAnalyzer(BaseAnalyzer):
    """A fake analyzer for testing the pipeline."""

    def __init__(self, name: str, score: float, explanation: str = "Test", flags=None, enabled=True):
        self._name = name
        self._score = score
        self._explanation = explanation
        self._flags = flags or []
        self._enabled = enabled

    @property
    def name(self) -> str:
        return self._name

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def analyze(self, transaction: dict) -> RiskAssessment:
        return RiskAssessment(
            riskScore=self._score,
            explanation=self._explanation,
            flags=self._flags,
        )
