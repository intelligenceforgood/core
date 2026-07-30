"""Unit tests for scope enforcement middleware."""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from i4g.api.middleware.scope_middleware import require_scope

app = FastAPI()


@app.get("/test-scope", dependencies=[Depends(require_scope("partner:feed"))])
def _scoped_endpoint_route():
    return {"status": "ok"}


client = TestClient(app)


def test_scope_middleware_admin_bypass(monkeypatch: pytest.MonkeyPatch) -> None:
    """Admin role bypasses scope checks even without matching scope."""
    from i4g.api.auth import require_token

    def mock_admin():
        return {"username": "admin-user", "role": "admin", "scopes": []}

    app.dependency_overrides[require_token] = mock_admin
    try:
        response = client.get("/test-scope")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
    finally:
        app.dependency_overrides.clear()


def test_scope_middleware_matching_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    """User with matching scope gets access."""
    from i4g.api.auth import require_token

    def mock_partner_user():
        return {"username": "partner-user", "role": "user", "scopes": ["partner:feed", "cases:read"]}

    app.dependency_overrides[require_token] = mock_partner_user
    try:
        response = client.get("/test-scope")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
    finally:
        app.dependency_overrides.clear()


def test_scope_middleware_missing_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    """User without matching scope gets 403."""
    from i4g.api.auth import require_token

    def mock_limited_user():
        return {"username": "limited-user", "role": "user", "scopes": ["cases:read"]}

    app.dependency_overrides[require_token] = mock_limited_user
    try:
        response = client.get("/test-scope")
        assert response.status_code == 403
        assert "Insufficient scope" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_scope_middleware_wildcard_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    """User with wildcard '*' scope gets access."""
    from i4g.api.auth import require_token

    def mock_wildcard_user():
        return {"username": "wildcard-user", "role": "user", "scopes": ["*"]}

    app.dependency_overrides[require_token] = mock_wildcard_user
    try:
        response = client.get("/test-scope")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
    finally:
        app.dependency_overrides.clear()
