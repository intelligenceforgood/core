"""Unit tests for the accounts management API (WS-5: F34, F35).

Tests verify admin-only access, self-service /me endpoint,
role changes, and deactivation through the API.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from i4g.api.accounts import get_account_store, router
from i4g.api.app import app
from i4g.api.auth import require_role, require_token


@pytest.fixture(autouse=True)
def clear_rate_limit():
    from i4g.api import app as app_module

    app_module.REQUEST_LOG.clear()
    yield
    app_module.REQUEST_LOG.clear()


def _mock_store():
    """Create a mock AccountStore."""
    store = MagicMock()
    store.get_or_create_account.return_value = {
        "email": "analyst@test.io",
        "role": "analyst",
        "display_name": "Test Analyst",
        "is_active": True,
    }
    store.get_account.return_value = {
        "email": "analyst@test.io",
        "role": "analyst",
        "display_name": "Test Analyst",
        "is_active": True,
    }
    store.list_accounts.return_value = [
        {"email": "analyst@test.io", "role": "analyst", "display_name": "A", "is_active": True},
        {"email": "admin@test.io", "role": "admin", "display_name": "B", "is_active": True},
    ]
    store.update_role.return_value = {
        "email": "analyst@test.io",
        "role": "admin",
        "display_name": "A",
        "is_active": True,
    }
    store.deactivate_account.return_value = True
    return store


class TestAccountsMe:
    """GET /accounts/me — available to any authenticated user."""

    def test_me_returns_current_user(self):
        mock_store = _mock_store()
        app.dependency_overrides[require_token] = lambda: {"username": "analyst@test.io", "role": "analyst"}
        app.dependency_overrides[get_account_store] = lambda: mock_store

        client = TestClient(app)
        r = client.get("/accounts/me")
        assert r.status_code == 200
        body = r.json()
        assert body["email"] == "analyst@test.io"
        assert body["role"] == "analyst"
        assert body["displayName"] == "Test Analyst"

        app.dependency_overrides.clear()


class TestAccountsList:
    """GET /accounts — admin-only."""

    def test_admin_can_list_accounts(self):
        mock_store = _mock_store()
        app.dependency_overrides[require_token] = lambda: {"username": "admin@test.io", "role": "admin"}
        app.dependency_overrides[get_account_store] = lambda: mock_store

        client = TestClient(app)
        r = client.get("/accounts")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 2
        assert len(body["items"]) == 2

        app.dependency_overrides.clear()

    def test_analyst_cannot_list_accounts(self):
        mock_store = _mock_store()
        app.dependency_overrides[require_token] = lambda: {"username": "analyst@test.io", "role": "analyst"}
        app.dependency_overrides[get_account_store] = lambda: mock_store

        client = TestClient(app)
        r = client.get("/accounts")
        assert r.status_code == 403

        app.dependency_overrides.clear()

    def test_user_cannot_list_accounts(self):
        mock_store = _mock_store()
        app.dependency_overrides[require_token] = lambda: {"username": "user@test.io", "role": "user"}
        app.dependency_overrides[get_account_store] = lambda: mock_store

        client = TestClient(app)
        r = client.get("/accounts")
        assert r.status_code == 403

        app.dependency_overrides.clear()


class TestUpdateRole:
    """PUT /accounts/{email}/role — admin-only, F34, F35."""

    def test_admin_can_change_role(self):
        mock_store = _mock_store()
        app.dependency_overrides[require_token] = lambda: {"username": "admin@test.io", "role": "admin"}
        app.dependency_overrides[get_account_store] = lambda: mock_store

        client = TestClient(app)
        r = client.put("/accounts/analyst@test.io/role", json={"role": "admin"})
        assert r.status_code == 200
        body = r.json()
        assert body["updated"] is True
        assert body["oldRole"] == "analyst"
        assert body["newRole"] == "admin"

        app.dependency_overrides.clear()

    def test_analyst_cannot_change_role(self):
        mock_store = _mock_store()
        app.dependency_overrides[require_token] = lambda: {"username": "analyst@test.io", "role": "analyst"}
        app.dependency_overrides[get_account_store] = lambda: mock_store

        client = TestClient(app)
        r = client.put("/accounts/analyst@test.io/role", json={"role": "admin"})
        assert r.status_code == 403

        app.dependency_overrides.clear()

    def test_self_demotion_blocked(self):
        mock_store = _mock_store()
        app.dependency_overrides[require_token] = lambda: {"username": "admin@test.io", "role": "admin"}
        app.dependency_overrides[get_account_store] = lambda: mock_store

        client = TestClient(app)
        r = client.put("/accounts/admin@test.io/role", json={"role": "analyst"})
        assert r.status_code == 400
        assert "own admin role" in r.json()["detail"]

        app.dependency_overrides.clear()

    def test_role_change_nonexistent_user(self):
        mock_store = _mock_store()
        mock_store.get_account.return_value = None
        app.dependency_overrides[require_token] = lambda: {"username": "admin@test.io", "role": "admin"}
        app.dependency_overrides[get_account_store] = lambda: mock_store

        client = TestClient(app)
        r = client.put("/accounts/nobody@test.io/role", json={"role": "admin"})
        assert r.status_code == 404

        app.dependency_overrides.clear()

    def test_invalid_role_value(self):
        mock_store = _mock_store()
        mock_store.update_role.side_effect = ValueError("Invalid role: 'superuser'")
        app.dependency_overrides[require_token] = lambda: {"username": "admin@test.io", "role": "admin"}
        app.dependency_overrides[get_account_store] = lambda: mock_store

        client = TestClient(app)
        r = client.put("/accounts/analyst@test.io/role", json={"role": "superuser"})
        assert r.status_code == 400
        assert "Invalid role" in r.json()["detail"]

        app.dependency_overrides.clear()


class TestDeactivateAccount:
    """PUT /accounts/{email}/deactivate — admin-only."""

    def test_admin_can_deactivate(self):
        mock_store = _mock_store()
        app.dependency_overrides[require_token] = lambda: {"username": "admin@test.io", "role": "admin"}
        app.dependency_overrides[get_account_store] = lambda: mock_store

        client = TestClient(app)
        r = client.put("/accounts/analyst@test.io/deactivate")
        assert r.status_code == 200
        assert r.json()["deactivated"] is True

        app.dependency_overrides.clear()

    def test_cannot_deactivate_self(self):
        mock_store = _mock_store()
        app.dependency_overrides[require_token] = lambda: {"username": "admin@test.io", "role": "admin"}
        app.dependency_overrides[get_account_store] = lambda: mock_store

        client = TestClient(app)
        r = client.put("/accounts/admin@test.io/deactivate")
        assert r.status_code == 400

        app.dependency_overrides.clear()

    def test_deactivate_nonexistent(self):
        mock_store = _mock_store()
        mock_store.deactivate_account.return_value = False
        app.dependency_overrides[require_token] = lambda: {"username": "admin@test.io", "role": "admin"}
        app.dependency_overrides[get_account_store] = lambda: mock_store

        client = TestClient(app)
        r = client.put("/accounts/nobody@test.io/deactivate")
        assert r.status_code == 404

        app.dependency_overrides.clear()


class TestReactivateAccount:
    """PUT /accounts/{email}/reactivate — admin-only."""

    def test_admin_can_reactivate(self):
        mock_store = _mock_store()
        mock_store.reactivate_account.return_value = True
        app.dependency_overrides[require_token] = lambda: {"username": "admin@test.io", "role": "admin"}
        app.dependency_overrides[get_account_store] = lambda: mock_store

        client = TestClient(app)
        r = client.put("/accounts/analyst@test.io/reactivate")
        assert r.status_code == 200
        assert r.json()["reactivated"] is True

        app.dependency_overrides.clear()

    def test_analyst_cannot_reactivate(self):
        mock_store = _mock_store()
        app.dependency_overrides[require_token] = lambda: {"username": "analyst@test.io", "role": "analyst"}
        app.dependency_overrides[get_account_store] = lambda: mock_store

        client = TestClient(app)
        r = client.put("/accounts/someone@test.io/reactivate")
        assert r.status_code == 403

        app.dependency_overrides.clear()

    def test_reactivate_nonexistent(self):
        mock_store = _mock_store()
        mock_store.reactivate_account.return_value = False
        app.dependency_overrides[require_token] = lambda: {"username": "admin@test.io", "role": "admin"}
        app.dependency_overrides[get_account_store] = lambda: mock_store

        client = TestClient(app)
        r = client.put("/accounts/nobody@test.io/reactivate")
        assert r.status_code == 404

        app.dependency_overrides.clear()
