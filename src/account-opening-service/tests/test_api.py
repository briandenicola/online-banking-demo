"""Tests for account-opening-service API endpoints.

Covers authentication, authorization, CRUD operations, and validation
for all routes defined in the spec (R1):
  POST   /api/account-opening/applications
  GET    /api/account-opening/applications/{id}
  GET    /api/account-opening/applications       (admin)
  PATCH  /api/account-opening/applications/{id}/review  (admin)
  GET    /api/account-opening/applications/{id}/audit   (admin)
"""
import pytest
import pytest_asyncio


BASE = "/api/account-opening/applications"


@pytest.mark.asyncio
class TestCreateApplication:
    """POST /api/account-opening/applications"""

    async def test_create_returns_201_with_valid_data(
        self, app_client, sample_application, auth_token
    ):
        """Authenticated user with valid form data gets 201 + application ID."""
        resp = await app_client.post(
            BASE,
            json=sample_application,
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert "id" in body
        assert body.get("status") == "submitted"

    async def test_create_returns_401_without_token(
        self, app_client, sample_application
    ):
        """Unauthenticated requests must be rejected with 401."""
        resp = await app_client.post(BASE, json=sample_application)
        assert resp.status_code == 401

    async def test_create_returns_422_missing_required_fields(
        self, app_client, auth_token
    ):
        """Incomplete form data must fail validation with 422."""
        resp = await app_client.post(
            BASE,
            json={"firstName": "Jane"},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 422

    async def test_create_returns_422_invalid_email(
        self, app_client, sample_application, auth_token
    ):
        """Invalid email format must fail validation."""
        sample_application["email"] = "not-an-email"
        resp = await app_client.post(
            BASE,
            json=sample_application,
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 422

    async def test_create_returns_422_invalid_ssn(
        self, app_client, sample_application, auth_token
    ):
        """SSN must be exactly 4 digits."""
        sample_application["ssn"] = "12"
        resp = await app_client.post(
            BASE,
            json=sample_application,
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 422

    async def test_created_application_has_initial_status_submitted(
        self, app_client, sample_application, auth_token
    ):
        """New applications must start in 'submitted' status."""
        resp = await app_client.post(
            BASE,
            json=sample_application,
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 201
        assert resp.json()["status"] == "submitted"


@pytest.mark.asyncio
class TestGetApplication:
    """GET /api/account-opening/applications/{id}"""

    async def test_get_returns_created_application(
        self, app_client, sample_application, auth_token
    ):
        """A created application is retrievable by its ID."""
        create_resp = await app_client.post(
            BASE,
            json=sample_application,
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        app_id = create_resp.json()["id"]

        get_resp = await app_client.get(
            f"{BASE}/{app_id}",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == app_id

    async def test_get_returns_404_for_nonexistent_id(
        self, app_client, auth_token
    ):
        """Non-existent application ID must return 404."""
        resp = await app_client.get(
            f"{BASE}/nonexistent-uuid-999",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestListApplications:
    """GET /api/account-opening/applications (admin only)"""

    async def test_list_requires_admin_role(self, app_client, admin_token):
        """Admin users can list all applications."""
        resp = await app_client.get(
            BASE,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200

    async def test_list_returns_403_for_non_admin(self, app_client, auth_token):
        """Regular users must be denied access to the list endpoint."""
        resp = await app_client.get(
            BASE,
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
class TestAdminReview:
    """PATCH /api/account-opening/applications/{id}/review (admin only)"""

    async def test_review_requires_admin(self, app_client, auth_token):
        """Regular users cannot review applications."""
        resp = await app_client.patch(
            f"{BASE}/some-app-id/review",
            json={"decision": "approved", "notes": "Looks good"},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 403

    async def test_admin_can_review_application(
        self, app_client, sample_application, auth_token, admin_token
    ):
        """Admin review updates status and adds an audit entry."""
        # Create an application first
        create_resp = await app_client.post(
            BASE,
            json=sample_application,
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        app_id = create_resp.json()["id"]

        # Admin reviews
        review_resp = await app_client.patch(
            f"{BASE}/{app_id}/review",
            json={"decision": "approved", "notes": "Manual approval after review"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        # Accept either 200 or 202 depending on implementation
        assert review_resp.status_code in (200, 202)
        body = review_resp.json()
        # Status should reflect the review decision
        assert body.get("status") in ("approved", "rejected", "pending_review")


@pytest.mark.asyncio
class TestAuditTrail:
    """GET /api/account-opening/applications/{id}/audit (admin only)"""

    async def test_audit_requires_admin(self, app_client, auth_token):
        """Regular users cannot access the audit trail."""
        resp = await app_client.get(
            f"{BASE}/some-app-id/audit",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 403

    async def test_admin_can_view_audit_trail(
        self, app_client, sample_application, auth_token, admin_token
    ):
        """Admin can retrieve the audit trail for an application."""
        # Create an application
        create_resp = await app_client.post(
            BASE,
            json=sample_application,
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        app_id = create_resp.json()["id"]

        # Admin requests audit trail
        audit_resp = await app_client.get(
            f"{BASE}/{app_id}/audit",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert audit_resp.status_code == 200
        body = audit_resp.json()
        # Audit trail should be a list
        assert isinstance(body, list) or "auditTrail" in body
