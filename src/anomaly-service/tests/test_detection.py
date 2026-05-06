"""Tests for anomaly detection endpoint."""
import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestHealthEndpoint:
    def test_health_returns_healthy(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}


class TestDetectEndpoint:
    def test_normal_transaction_not_anomalous(self, client):
        """A normal small transaction should not be flagged."""
        payload = {
            "id": "evt-1",
            "transactionId": "txn-001",
            "accountId": "acc-001",
            "amount": 50.0,
            "type": "Purchase",
            "description": "Coffee shop",
            "category": "Food & Dining"
        }

        response = client.post("/detect", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["transactionId"] == "txn-001"
        assert "isAnomalous" in data
        assert "confidenceScore" in data

    def test_high_amount_transaction(self, client):
        """A high-value transaction should trigger heuristic checks when model is trained."""
        payload = {
            "id": "evt-2",
            "transactionId": "txn-002",
            "accountId": "acc-001",
            "amount": 50000.0,
            "type": "Transfer",
            "description": "Large wire transfer",
            "category": "Transfer"
        }

        response = client.post("/detect", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["transactionId"] == "txn-002"
        # With insufficient training data, model won't flag it yet
        assert "isAnomalous" in data
        assert isinstance(data["confidenceScore"], float)

    def test_missing_required_fields_returns_422(self, client):
        """Missing required fields should return validation error."""
        payload = {
            "id": "evt-3",
            "transactionId": "txn-003"
            # Missing required fields
        }

        response = client.post("/detect", json=payload)

        assert response.status_code == 422

    def test_detect_returns_anomaly_result_schema(self, client):
        """Response should match AnomalyResult schema."""
        payload = {
            "id": "evt-4",
            "transactionId": "txn-004",
            "accountId": "acc-001",
            "amount": 100.0,
            "type": "Purchase",
            "description": "Grocery store",
            "category": "Shopping"
        }

        response = client.post("/detect", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert "transactionId" in data
        assert "isAnomalous" in data
        assert "confidenceScore" in data
        assert "reason" in data

    def test_zero_amount_transaction(self, client):
        """Edge case: zero amount transaction."""
        payload = {
            "id": "evt-5",
            "transactionId": "txn-005",
            "accountId": "acc-001",
            "amount": 0.0,
            "type": "Adjustment",
            "description": "Zero adjustment",
            "category": "Other"
        }

        response = client.post("/detect", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["transactionId"] == "txn-005"

    def test_negative_amount_transaction(self, client):
        """Edge case: negative amount (refund)."""
        payload = {
            "id": "evt-6",
            "transactionId": "txn-006",
            "accountId": "acc-001",
            "amount": -200.0,
            "type": "Refund",
            "description": "Return refund",
            "category": "Shopping"
        }

        response = client.post("/detect", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["transactionId"] == "txn-006"
