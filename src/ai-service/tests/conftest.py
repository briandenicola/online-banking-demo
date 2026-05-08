import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from app.main import (
    RiskAssessment,
    FoundryRiskAnalyzer,
    AnalyzerPipeline,
    BaseAnalyzer,
)


@pytest.fixture
def client():
    """Create a test client for the anomaly service (no lifespan — no Redis/Foundry)."""
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


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
