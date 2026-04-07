"""Unit tests for the EngagementScopeMiddleware."""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from i4g.api.middleware.engagement import EngagementScopeMiddleware


@pytest.fixture
def test_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(EngagementScopeMiddleware)

    @app.get("/test")
    def _handler(request: Request):
        return {"engagement_id": request.state.engagement_id}

    return app


def test_no_header_sets_none(test_app):
    client = TestClient(test_app)
    r = client.get("/test")
    assert r.status_code == 200
    assert r.json()["engagement_id"] is None


def test_valid_uuid_header(test_app):
    client = TestClient(test_app)
    eid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    r = client.get("/test", headers={"X-Engagement-Id": eid})
    assert r.status_code == 200
    assert r.json()["engagement_id"] == eid


def test_invalid_uuid_returns_400(test_app):
    client = TestClient(test_app)
    r = client.get("/test", headers={"X-Engagement-Id": "not-a-uuid"})
    assert r.status_code == 400
    assert "Invalid" in r.json()["detail"]


def test_empty_header_treated_as_absent(test_app):
    client = TestClient(test_app)
    r = client.get("/test", headers={"X-Engagement-Id": ""})
    assert r.status_code == 200
    assert r.json()["engagement_id"] is None
