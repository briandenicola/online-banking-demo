import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client for the budget service."""
    from app.main import app
    return TestClient(app)
