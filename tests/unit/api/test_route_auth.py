"""Unit tests for route-level role enforcement (WS-5: F32).

Verifies that admin-only endpoints (campaigns create/update, task update)
reject non-admin users with 403.
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from i4g.api.app import app
from i4g.api.auth import require_token


@pytest.fixture(autouse=True)
def clear_overrides():
    app.dependency_overrides.clear()
    from i4g.api import app as app_module

    app_module.REQUEST_LOG.clear()
    yield
    app.dependency_overrides.clear()
    app_module.REQUEST_LOG.clear()


class TestCampaignRouteAuth:
    """Campaign create/update require admin role."""

    def test_analyst_can_list_campaigns(self):
        """GET /campaigns (read) is available to any authenticated user."""
        app.dependency_overrides[require_token] = lambda: {"username": "analyst@test.io", "role": "analyst"}
        # We need to mock the campaigns service dependency
        from i4g.api.campaigns import get_service

        mock_svc = MagicMock()
        mock_svc.list_active_campaigns.return_value = []
        app.dependency_overrides[get_service] = lambda: mock_svc

        client = TestClient(app)
        r = client.get("/campaigns")
        assert r.status_code == 200

    def test_analyst_cannot_create_campaign(self):
        """POST /campaigns requires admin."""
        app.dependency_overrides[require_token] = lambda: {"username": "analyst@test.io", "role": "analyst"}
        client = TestClient(app)
        r = client.post(
            "/campaigns",
            json={"name": "Test", "description": "d", "taxonomy_labels": {}},
        )
        assert r.status_code == 403

    def test_admin_can_create_campaign(self):
        """POST /campaigns succeeds for admin."""
        app.dependency_overrides[require_token] = lambda: {"username": "admin@test.io", "role": "admin"}
        from i4g.api.campaigns import get_service

        mock_svc = MagicMock()
        mock_svc.create_campaign.return_value = "camp-1"
        app.dependency_overrides[get_service] = lambda: mock_svc

        client = TestClient(app)
        r = client.post(
            "/campaigns",
            json={"name": "Test", "description": "d", "taxonomy_labels": {}},
        )
        assert r.status_code == 200

    def test_analyst_cannot_update_campaign(self):
        """PATCH /campaigns/{id} requires admin."""
        app.dependency_overrides[require_token] = lambda: {"username": "analyst@test.io", "role": "analyst"}
        client = TestClient(app)
        r = client.patch("/campaigns/camp-1", json={"name": "Updated"})
        assert r.status_code == 403

    def test_user_cannot_create_campaign(self):
        """User role also rejected."""
        app.dependency_overrides[require_token] = lambda: {"username": "user@test.io", "role": "user"}
        client = TestClient(app)
        r = client.post(
            "/campaigns",
            json={"name": "Test", "description": "d", "taxonomy_labels": {}},
        )
        assert r.status_code == 403


class TestTaskUpdateAuth:
    """POST /tasks/{id}/update requires any valid token (API key or IAP)."""

    def test_admin_can_update_task(self):
        app.dependency_overrides[require_token] = lambda: {"username": "admin@test.io", "role": "admin"}
        client = TestClient(app)
        r = client.post("/tasks/task-1/update", json={"status": "done", "message": "ok"})
        assert r.status_code == 200

    def test_analyst_can_update_task(self):
        """Any authenticated user can update task status (SSI TaskStatusReporter uses API key)."""
        app.dependency_overrides[require_token] = lambda: {"username": "analyst@test.io", "role": "analyst"}
        client = TestClient(app)
        r = client.post("/tasks/task-1/update", json={"status": "done"})
        assert r.status_code == 200
