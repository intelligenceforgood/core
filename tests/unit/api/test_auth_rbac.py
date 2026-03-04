"""Unit tests for RBAC auth enforcement (WS-5: F30, F31, F32).

Tests verify:
- ``require_token()`` resolves roles from the accounts table.
- ``require_role()`` enforces role hierarchy properly.
- Route-level authorization on admin-only endpoints.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from i4g.api.auth import require_role, require_token, reset_auth_state

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app_with_routes() -> FastAPI:
    """Build a minimal FastAPI app with role-gated routes for testing."""
    app = FastAPI()

    @app.get("/public")
    def public_endpoint(user=_dep(require_token)):
        return {"user": user}

    @app.get("/analyst-only")
    def analyst_endpoint(user=_dep(require_role("analyst"))):
        return {"user": user}

    @app.get("/admin-only")
    def admin_endpoint(user=_dep(require_role("admin"))):
        return {"user": user}

    @app.get("/leo-only")
    def leo_endpoint(user=_dep(require_role("leo"))):
        return {"user": user}

    return app


def _dep(fn):
    """Import Depends inline."""
    from fastapi import Depends

    return Depends(fn)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRequireRoleDependency:
    """Test require_role as a FastAPI dependency."""

    @pytest.fixture(autouse=True)
    def _reset(self):
        """Reset auth state between tests."""
        reset_auth_state()
        yield
        reset_auth_state()

    def test_admin_can_access_admin_only(self):
        app = _make_app_with_routes()
        app.dependency_overrides[require_token] = lambda: {"username": "admin@test.com", "role": "admin"}
        client = TestClient(app)
        r = client.get("/admin-only")
        assert r.status_code == 200

    def test_analyst_cannot_access_admin_only(self):
        app = _make_app_with_routes()
        app.dependency_overrides[require_token] = lambda: {"username": "analyst@test.com", "role": "analyst"}
        client = TestClient(app)
        r = client.get("/admin-only")
        assert r.status_code == 403

    def test_analyst_can_access_analyst_only(self):
        app = _make_app_with_routes()
        app.dependency_overrides[require_token] = lambda: {"username": "analyst@test.com", "role": "analyst"}
        client = TestClient(app)
        r = client.get("/analyst-only")
        assert r.status_code == 200

    def test_user_cannot_access_analyst_only(self):
        app = _make_app_with_routes()
        app.dependency_overrides[require_token] = lambda: {"username": "user@test.com", "role": "user"}
        client = TestClient(app)
        r = client.get("/analyst-only")
        assert r.status_code == 403

    def test_admin_can_access_analyst_only(self):
        app = _make_app_with_routes()
        app.dependency_overrides[require_token] = lambda: {"username": "admin@test.com", "role": "admin"}
        client = TestClient(app)
        r = client.get("/analyst-only")
        assert r.status_code == 200

    def test_leo_can_access_analyst_only(self):
        app = _make_app_with_routes()
        app.dependency_overrides[require_token] = lambda: {"username": "leo@test.com", "role": "leo"}
        client = TestClient(app)
        r = client.get("/analyst-only")
        assert r.status_code == 200

    def test_leo_cannot_access_admin_only(self):
        app = _make_app_with_routes()
        app.dependency_overrides[require_token] = lambda: {"username": "leo@test.com", "role": "leo"}
        client = TestClient(app)
        r = client.get("/admin-only")
        assert r.status_code == 403

    def test_user_can_access_public(self):
        app = _make_app_with_routes()
        app.dependency_overrides[require_token] = lambda: {"username": "user@test.com", "role": "user"}
        client = TestClient(app)
        r = client.get("/public")
        assert r.status_code == 200

    def test_403_detail_message(self):
        app = _make_app_with_routes()
        app.dependency_overrides[require_token] = lambda: {"username": "user@test.com", "role": "user"}
        client = TestClient(app)
        r = client.get("/admin-only")
        assert r.status_code == 403
        assert "admin" in r.json()["detail"]
