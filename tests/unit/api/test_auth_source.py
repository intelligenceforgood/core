"""Unit tests for auth_source tagging in require_token."""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from i4g.api.auth import require_token, reset_auth_state
from i4g.settings import get_settings


@pytest.fixture(autouse=True)
def _reset():
    """Reset auth state between tests."""
    reset_auth_state()
    yield
    reset_auth_state()


def _make_app() -> FastAPI:
    app = FastAPI()

    @app.get("/me")
    def me(user=Depends(require_token)):
        return user

    return app


def test_auth_source_local(monkeypatch):
    """Local dev / auth disabled produces auth_source='local'."""
    settings = get_settings()
    monkeypatch.setattr(settings.identity, "disable_auth", True)

    client = TestClient(_make_app())
    response = client.get("/me")
    assert response.status_code == 200
    data = response.json()
    assert data["auth_source"] == "local"
    assert data["username"] == "local-dev"


def test_auth_source_static_key(monkeypatch):
    """Env-var API key produces auth_source='static_key'."""
    settings = get_settings()
    monkeypatch.setattr(settings.identity, "disable_auth", False)
    monkeypatch.setattr(settings.api, "key", "test-secret-key")

    client = TestClient(_make_app())
    response = client.get("/me", headers={"X-API-KEY": "test-secret-key"})
    assert response.status_code == 200
    data = response.json()
    assert data["auth_source"] == "static_key"
    assert data["username"] == "service"


def test_auth_source_db_api_key(monkeypatch):
    """DB-backed API key lookup produces auth_source='db_api_key'."""
    settings = get_settings()
    monkeypatch.setattr(settings.identity, "disable_auth", False)
    monkeypatch.setattr(settings.api, "key", "test-secret-key")

    def mock_validate(key):
        if key == "db-key-123":
            return {
                "key_id": "k123",
                "owner_email": "partner@example.com",
                "key_type": "partner",
                "scopes": ["cases:read"],
            }
        return None

    monkeypatch.setattr("i4g.api.auth._validate_db_api_key", mock_validate)
    monkeypatch.setattr("i4g.api.auth._resolve_role", lambda email: "analyst")

    client = TestClient(_make_app())
    response = client.get("/me", headers={"X-API-KEY": "db-key-123"})
    assert response.status_code == 200
    data = response.json()
    assert data["auth_source"] == "db_api_key"
    assert data["username"] == "partner@example.com"
    assert data["scopes"] == ["cases:read"]


def test_auth_source_iap(monkeypatch):
    """IAP JWT assertion produces auth_source='iap'."""
    settings = get_settings()
    monkeypatch.setattr(settings.identity, "disable_auth", False)
    monkeypatch.setattr(settings.api, "key", "test-secret-key")

    def mock_verify_iap(token, is_iap_assertion=False):
        if is_iap_assertion and token == "fake-iap-jwt":
            return {"username": "iap-user@example.com", "role": "analyst"}
        return None

    monkeypatch.setattr("i4g.api.auth._verify_iap_jwt", mock_verify_iap)

    client = TestClient(_make_app())
    response = client.get("/me", headers={"X-Goog-IAP-JWT-Assertion": "fake-iap-jwt"})
    assert response.status_code == 200
    data = response.json()
    assert data["auth_source"] == "iap"
    assert data["username"] == "iap-user@example.com"


def test_auth_source_bearer(monkeypatch):
    """Bearer token produces auth_source='bearer'."""
    settings = get_settings()
    monkeypatch.setattr(settings.identity, "disable_auth", False)
    monkeypatch.setattr(settings.api, "key", "test-secret-key")

    def mock_verify_iap(token, is_iap_assertion=False):
        if not is_iap_assertion and token == "fake-bearer-token":
            return {"username": "bearer-user@example.com", "role": "analyst"}
        return None

    monkeypatch.setattr("i4g.api.auth._verify_iap_jwt", mock_verify_iap)

    client = TestClient(_make_app())
    response = client.get("/me", headers={"Authorization": "Bearer fake-bearer-token"})
    assert response.status_code == 200
    data = response.json()
    assert data["auth_source"] == "bearer"
    assert data["username"] == "bearer-user@example.com"
