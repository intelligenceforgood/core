"""Unit tests for the engagements API router."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from i4g.api.app import app
from i4g.api.auth import require_token
from i4g.api.engagements import get_engagement_store


@pytest.fixture(autouse=True)
def clear_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def _mock_store() -> MagicMock:
    return MagicMock()


def _as_instructor():
    app.dependency_overrides[require_token] = lambda: {"username": "instructor@test.io", "role": "instructor"}


def _as_analyst():
    app.dependency_overrides[require_token] = lambda: {"username": "analyst@test.io", "role": "analyst"}


def _as_admin():
    app.dependency_overrides[require_token] = lambda: {"username": "admin@test.io", "role": "admin"}


def _as_user():
    app.dependency_overrides[require_token] = lambda: {"username": "user@test.io", "role": "user"}


class TestCreateEngagement:
    def test_instructor_can_create(self):
        _as_instructor()
        store = _mock_store()
        store.create.return_value = {
            "engagement_id": "eng-1",
            "name": "Spring 2026",
            "description": None,
            "status": "draft",
            "starts_at": None,
            "ends_at": None,
            "created_by": "instructor@test.io",
            "metadata": None,
            "created_at": "2026-04-07T00:00:00+00:00",
            "updated_at": "2026-04-07T00:00:00+00:00",
        }
        app.dependency_overrides[get_engagement_store] = lambda: store
        client = TestClient(app)
        r = client.post("/engagements", json={"name": "Spring 2026"})
        assert r.status_code == 201
        assert r.json()["engagementId"] == "eng-1"

    def test_analyst_cannot_create(self):
        _as_analyst()
        client = TestClient(app)
        r = client.post("/engagements", json={"name": "Nope"})
        assert r.status_code == 403

    def test_user_cannot_create(self):
        _as_user()
        client = TestClient(app)
        r = client.post("/engagements", json={"name": "Nope"})
        assert r.status_code == 403

    def test_admin_can_create(self):
        _as_admin()
        store = _mock_store()
        store.create.return_value = {
            "engagement_id": "eng-2",
            "name": "Admin Eng",
            "description": None,
            "status": "draft",
            "starts_at": None,
            "ends_at": None,
            "created_by": "admin@test.io",
            "metadata": None,
            "created_at": "2026-04-07T00:00:00+00:00",
            "updated_at": "2026-04-07T00:00:00+00:00",
        }
        app.dependency_overrides[get_engagement_store] = lambda: store
        client = TestClient(app)
        r = client.post("/engagements", json={"name": "Admin Eng"})
        assert r.status_code == 201


class TestListEngagements:
    def test_analyst_can_list(self):
        _as_analyst()
        store = _mock_store()
        store.list.return_value = []
        app.dependency_overrides[get_engagement_store] = lambda: store
        client = TestClient(app)
        r = client.get("/engagements")
        assert r.status_code == 200
        assert r.json() == []

    def test_user_cannot_list(self):
        _as_user()
        client = TestClient(app)
        r = client.get("/engagements")
        assert r.status_code == 403


class TestGetEngagement:
    def test_analyst_can_get(self):
        _as_analyst()
        store = _mock_store()
        store.get.return_value = {
            "engagement_id": "eng-1",
            "name": "Test",
            "description": None,
            "status": "active",
            "starts_at": None,
            "ends_at": None,
            "created_by": "admin@test.io",
            "metadata": None,
            "created_at": "2026-04-07T00:00:00+00:00",
            "updated_at": "2026-04-07T00:00:00+00:00",
        }
        app.dependency_overrides[get_engagement_store] = lambda: store
        client = TestClient(app)
        r = client.get("/engagements/eng-1")
        assert r.status_code == 200
        assert r.json()["name"] == "Test"

    def test_not_found(self):
        _as_analyst()
        store = _mock_store()
        store.get.return_value = None
        app.dependency_overrides[get_engagement_store] = lambda: store
        client = TestClient(app)
        r = client.get("/engagements/nonexistent")
        assert r.status_code == 404


class TestUpdateEngagement:
    def test_instructor_can_update(self):
        _as_instructor()
        store = _mock_store()
        store.update.return_value = {
            "engagement_id": "eng-1",
            "name": "Updated",
            "description": None,
            "status": "active",
            "starts_at": None,
            "ends_at": None,
            "created_by": "admin@test.io",
            "metadata": None,
            "created_at": "2026-04-07T00:00:00+00:00",
            "updated_at": "2026-04-07T00:00:00+00:00",
        }
        app.dependency_overrides[get_engagement_store] = lambda: store
        client = TestClient(app)
        r = client.patch("/engagements/eng-1", json={"name": "Updated"})
        assert r.status_code == 200

    def test_analyst_cannot_update(self):
        _as_analyst()
        client = TestClient(app)
        r = client.patch("/engagements/eng-1", json={"name": "x"})
        assert r.status_code == 403


class TestDeleteEngagement:
    def test_admin_can_delete(self):
        _as_admin()
        store = _mock_store()
        store.archive.return_value = {"engagement_id": "eng-1", "status": "archived"}
        app.dependency_overrides[get_engagement_store] = lambda: store
        client = TestClient(app)
        r = client.delete("/engagements/eng-1")
        assert r.status_code == 204

    def test_instructor_cannot_delete(self):
        _as_instructor()
        client = TestClient(app)
        r = client.delete("/engagements/eng-1")
        assert r.status_code == 403


class TestCaseAssignment:
    def test_assign_cases(self):
        _as_instructor()
        store = _mock_store()
        store.get.return_value = {"engagement_id": "eng-1", "name": "Test"}
        store.assign_cases.return_value = 3
        app.dependency_overrides[get_engagement_store] = lambda: store
        client = TestClient(app)
        r = client.post("/engagements/eng-1/cases", json={"case_ids": ["c1", "c2", "c3"]})
        assert r.status_code == 200
        assert r.json()["count"] == 3

    def test_remove_cases(self):
        _as_instructor()
        store = _mock_store()
        store.get.return_value = {"engagement_id": "eng-1", "name": "Test"}
        store.remove_cases.return_value = 1
        app.dependency_overrides[get_engagement_store] = lambda: store
        client = TestClient(app)
        r = client.request("DELETE", "/engagements/eng-1/cases", json={"case_ids": ["c1"]})
        assert r.status_code == 200
        assert r.json()["count"] == 1

    def test_assign_to_nonexistent_engagement(self):
        _as_instructor()
        store = _mock_store()
        store.get.return_value = None
        app.dependency_overrides[get_engagement_store] = lambda: store
        client = TestClient(app)
        r = client.post("/engagements/bad-id/cases", json={"case_ids": ["c1"]})
        assert r.status_code == 404


class TestSummary:
    def test_get_summary(self):
        _as_analyst()
        store = _mock_store()
        store.get_summary.return_value = {
            "engagement_id": "eng-1",
            "name": "Spring 2026",
            "description": None,
            "status": "active",
            "starts_at": None,
            "ends_at": None,
            "created_by": "admin@test.io",
            "metadata": None,
            "created_at": "2026-04-07T00:00:00+00:00",
            "updated_at": "2026-04-07T00:00:00+00:00",
            "case_count": 50,
            "cases_reviewed": 32,
            "cases_remaining": 18,
            "review_completion_pct": 64.0,
        }
        app.dependency_overrides[get_engagement_store] = lambda: store
        client = TestClient(app)
        r = client.get("/engagements/eng-1/summary")
        assert r.status_code == 200
        data = r.json()
        assert data["caseCount"] == 50
        assert data["reviewCompletionPct"] == 64.0
