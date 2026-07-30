"""Unit tests for partner mode route filtering in create_app."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from i4g.api.app import create_app
from i4g.settings.config import reload_settings


def test_partner_mode_enabled_route_filtering(monkeypatch: pytest.MonkeyPatch) -> None:
    """When partner_mode=True, internal endpoints return 404, while partner/health endpoints remain accessible."""
    monkeypatch.setenv("I4G_API__PARTNER_MODE", "true")
    reload_settings(env="dev")

    app = create_app()
    client = TestClient(app)

    # Health endpoint should respond 200
    res_health = client.get("/health")
    assert res_health.status_code == 200
    assert res_health.json() == {"status": "ok"}

    # Partner feed endpoint route exists (returns 401/403/422 due to query/header requirements, NOT 404)
    res_feed = client.get("/feeds/indicators")
    assert res_feed.status_code != 404

    # Internal endpoints should not be registered (404)
    res_cases = client.get("/cases")
    assert res_cases.status_code == 404

    res_reviews = client.get("/reviews/search")
    assert res_reviews.status_code == 404


def test_partner_mode_disabled_all_routes_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """When partner_mode=False (default), all routes are accessible."""
    monkeypatch.setenv("I4G_API__PARTNER_MODE", "false")
    reload_settings(env="dev")

    app = create_app()
    client = TestClient(app)

    # Health endpoint responds 200
    res_health = client.get("/health")
    assert res_health.status_code == 200

    # Internal endpoint route exists (returns auth error, not 404)
    res_cases = client.get("/cases")
    assert res_cases.status_code != 404
