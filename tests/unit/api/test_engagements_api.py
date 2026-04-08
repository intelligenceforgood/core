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


def _as_manager():
    app.dependency_overrides[require_token] = lambda: {"username": "manager@test.io", "role": "manager"}


def _as_analyst():
    app.dependency_overrides[require_token] = lambda: {"username": "analyst@test.io", "role": "analyst"}


def _as_admin():
    app.dependency_overrides[require_token] = lambda: {"username": "admin@test.io", "role": "admin"}


def _as_user():
    app.dependency_overrides[require_token] = lambda: {"username": "user@test.io", "role": "user"}


class TestCreateEngagement:
    def test_manager_can_create(self):
        _as_manager()
        store = _mock_store()
        store.create.return_value = {
            "engagement_id": "eng-1",
            "name": "Spring 2026",
            "description": None,
            "status": "draft",
            "starts_at": None,
            "ends_at": None,
            "created_by": "manager@test.io",
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
    def test_manager_can_update(self):
        _as_manager()
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

    def test_manager_cannot_delete(self):
        _as_manager()
        client = TestClient(app)
        r = client.delete("/engagements/eng-1")
        assert r.status_code == 403


class TestCaseAssignment:
    def test_assign_cases(self):
        _as_manager()
        store = _mock_store()
        store.get.return_value = {"engagement_id": "eng-1", "name": "Test"}
        store.assign_cases.return_value = 3
        app.dependency_overrides[get_engagement_store] = lambda: store
        client = TestClient(app)
        r = client.post("/engagements/eng-1/cases", json={"case_ids": ["c1", "c2", "c3"]})
        assert r.status_code == 200
        assert r.json()["count"] == 3

    def test_remove_cases(self):
        _as_manager()
        store = _mock_store()
        store.get.return_value = {"engagement_id": "eng-1", "name": "Test"}
        store.remove_cases.return_value = 1
        app.dependency_overrides[get_engagement_store] = lambda: store
        client = TestClient(app)
        r = client.request("DELETE", "/engagements/eng-1/cases", json={"case_ids": ["c1"]})
        assert r.status_code == 200
        assert r.json()["count"] == 1

    def test_assign_to_nonexistent_engagement(self):
        _as_manager()
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


# ---------------------------------------------------------------------------
# Phase 3 — Analytics, Leaderboard, Export
# ---------------------------------------------------------------------------

_EXTENDED_SUMMARY = {
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
    "classification_distribution": {"phishing": 20, "scam": 12},
    "top_classifications": ["phishing", "scam"],
    "analyst_count": 5,
    "days_elapsed": 10,
    "days_remaining": 20,
    "avg_review_time_hours": 1.5,
}


class TestAnalytics:
    def test_analyst_can_get_analytics(self):
        _as_analyst()
        store = _mock_store()
        store.get_extended_summary.return_value = _EXTENDED_SUMMARY
        app.dependency_overrides[get_engagement_store] = lambda: store
        client = TestClient(app)
        r = client.get("/engagements/eng-1/analytics")
        assert r.status_code == 200
        data = r.json()
        assert data["classificationDistribution"] == {"phishing": 20, "scam": 12}
        assert data["analystCount"] == 5
        assert data["avgReviewTimeHours"] == 1.5

    def test_analytics_not_found(self):
        _as_analyst()
        store = _mock_store()
        store.get_extended_summary.return_value = None
        app.dependency_overrides[get_engagement_store] = lambda: store
        client = TestClient(app)
        r = client.get("/engagements/nonexistent/analytics")
        assert r.status_code == 404

    def test_user_cannot_get_analytics(self):
        _as_user()
        client = TestClient(app)
        r = client.get("/engagements/eng-1/analytics")
        assert r.status_code == 403


class TestLeaderboard:
    def test_analyst_can_get_leaderboard(self):
        _as_analyst()
        store = _mock_store()
        store.get_leaderboard.return_value = [
            {
                "rank": 1,
                "analyst_email": "alice@test.io",
                "cases_reviewed": 10,
                "avg_review_time_seconds": 300.0,
                "classification_accuracy": 0.92,
                "risk_score_mae": 5.0,
                "actions_logged": 20,
                "last_activity_at": "2026-04-07T00:00:00+00:00",
                "composite_score": 85.5,
            },
        ]
        app.dependency_overrides[get_engagement_store] = lambda: store
        client = TestClient(app)
        r = client.get("/engagements/eng-1/leaderboard")
        assert r.status_code == 200
        data = r.json()
        assert data["engagementId"] == "eng-1"
        assert data["totalAnalysts"] == 1
        assert data["entries"][0]["analystEmail"] == "alice@test.io"
        assert data["entries"][0]["compositeScore"] == 85.5

    def test_leaderboard_not_found(self):
        _as_analyst()
        store = _mock_store()
        store.get_leaderboard.return_value = None
        app.dependency_overrides[get_engagement_store] = lambda: store
        client = TestClient(app)
        r = client.get("/engagements/nonexistent/leaderboard")
        assert r.status_code == 404

    def test_user_cannot_get_leaderboard(self):
        _as_user()
        client = TestClient(app)
        r = client.get("/engagements/eng-1/leaderboard")
        assert r.status_code == 403


class TestExport:
    def test_manager_can_export_csv(self):
        _as_manager()
        store = _mock_store()
        store.get_extended_summary.return_value = _EXTENDED_SUMMARY
        store.get_leaderboard.return_value = [
            {
                "rank": 1,
                "analyst_email": "alice@test.io",
                "cases_reviewed": 10,
                "avg_review_time_seconds": 300.0,
                "classification_accuracy": 0.92,
                "risk_score_mae": 5.0,
                "actions_logged": 20,
                "composite_score": 85.5,
            },
        ]
        app.dependency_overrides[get_engagement_store] = lambda: store
        client = TestClient(app)
        r = client.get("/engagements/eng-1/export?fmt=csv")
        assert r.status_code == 200
        assert "text/csv" in r.headers["content-type"]
        assert "Rank" in r.text
        assert "alice@test.io" in r.text

    def test_manager_can_export_json(self):
        _as_manager()
        store = _mock_store()
        store.get_extended_summary.return_value = _EXTENDED_SUMMARY
        store.get_leaderboard.return_value = []
        app.dependency_overrides[get_engagement_store] = lambda: store
        client = TestClient(app)
        r = client.get("/engagements/eng-1/export?fmt=json")
        assert r.status_code == 200
        assert "application/json" in r.headers["content-type"]
        data = r.json()
        assert "summary" in data
        assert "leaderboard" in data

    def test_analyst_cannot_export(self):
        _as_analyst()
        client = TestClient(app)
        r = client.get("/engagements/eng-1/export")
        assert r.status_code == 403

    def test_export_not_found(self):
        _as_manager()
        store = _mock_store()
        store.get_extended_summary.return_value = None
        app.dependency_overrides[get_engagement_store] = lambda: store
        client = TestClient(app)
        r = client.get("/engagements/nonexistent/export")
        assert r.status_code == 404
