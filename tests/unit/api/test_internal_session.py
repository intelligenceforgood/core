"""Unit tests for require_internal_session dependency."""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from i4g.api.auth import require_token, reset_auth_state
from i4g.api.scopes import require_internal_session


@pytest.fixture(autouse=True)
def _reset():
    """Reset auth state between tests."""
    reset_auth_state()
    yield
    reset_auth_state()


def _make_app() -> FastAPI:
    app = FastAPI()

    @app.get("/internal-only", dependencies=[Depends(require_internal_session)])
    def internal_route():
        return {"ok": True}

    return app


def test_db_api_key_without_internal_scope_rejected():
    """DB API key without admin:internal scope gets HTTP 403."""
    app = _make_app()
    app.dependency_overrides[require_token] = lambda: {
        "username": "partner@example.com",
        "role": "admin",
        "auth_source": "db_api_key",
        "scopes": ["cases:read", "cases:write"],
    }
    client = TestClient(app)
    res = client.get("/internal-only")
    assert res.status_code == 403
    assert "API key access not permitted for this endpoint" in res.json()["detail"]


def test_db_api_key_with_internal_scope_allowed():
    """DB API key with admin:internal scope is allowed."""
    app = _make_app()
    app.dependency_overrides[require_token] = lambda: {
        "username": "admin-key@example.com",
        "role": "admin",
        "auth_source": "db_api_key",
        "scopes": ["cases:read", "admin:internal"],
    }
    client = TestClient(app)
    res = client.get("/internal-only")
    assert res.status_code == 200
    assert res.json() == {"ok": True}


def test_iap_auth_allowed():
    """IAP session bypasses internal session restriction."""
    app = _make_app()
    app.dependency_overrides[require_token] = lambda: {
        "username": "user@example.com",
        "role": "analyst",
        "auth_source": "iap",
    }
    client = TestClient(app)
    res = client.get("/internal-only")
    assert res.status_code == 200


def test_bearer_auth_allowed():
    """Bearer session bypasses internal session restriction."""
    app = _make_app()
    app.dependency_overrides[require_token] = lambda: {
        "username": "user@example.com",
        "role": "analyst",
        "auth_source": "bearer",
    }
    client = TestClient(app)
    res = client.get("/internal-only")
    assert res.status_code == 200


def test_static_key_allowed():
    """Static service key bypasses internal session restriction."""
    app = _make_app()
    app.dependency_overrides[require_token] = lambda: {
        "username": "service",
        "role": "admin",
        "auth_source": "static_key",
    }
    client = TestClient(app)
    res = client.get("/internal-only")
    assert res.status_code == 200


def test_local_dev_allowed():
    """Local dev session bypasses internal session restriction."""
    app = _make_app()
    app.dependency_overrides[require_token] = lambda: {
        "username": "local-dev",
        "role": "admin",
        "auth_source": "local",
    }
    client = TestClient(app)
    res = client.get("/internal-only")
    assert res.status_code == 200
