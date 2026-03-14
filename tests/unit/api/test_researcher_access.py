"""Tests for researcher role access control (S6-H5).

Verifies that endpoints returning individual case, review, or entity data
return 403 Forbidden when the authenticated user has only the ``researcher``
role.  Analyst and admin roles must still receive 200 / normal behavior.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from i4g.api.app import create_app
from i4g.api.auth import require_token
from i4g.api.intelligence import get_analytics_store, get_campaign_store

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(role: str = "researcher") -> dict[str, str]:
    return {"username": "test@example.com", "role": role}


RESEARCHER_USER = _make_user("researcher")
ANALYST_USER = _make_user("analyst")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_analytics_store() -> MagicMock:
    store = MagicMock()
    store.get_entity_stat.return_value = {
        "entity_type": "crypto_wallet",
        "canonical_value": "0xABC",
        "case_count": 3,
        "first_seen_at": "2025-01-01",
        "last_active_at": "2025-06-01",
        "loss_sum": 100000.0,
        "risk_score": 0.8,
        "status": "active",
        "case_ids": ["c1"],
        "campaign_ids": [],
    }
    store.get_entity_activity.return_value = [
        {"week": "2025-W01", "case_count": 1},
    ]
    store.get_entity_neighbors.return_value = []
    store.get_indicator_stat.return_value = {
        "indicator_id": "ind-001",
        "number": "192.168.1.1",
        "category": "ip",
        "case_count": 3,
        "loss_sum": 50000.0,
    }
    return store


@pytest.fixture()
def mock_campaign_store() -> MagicMock:
    store = MagicMock()
    store.get_campaign.return_value = None
    return store


def _build_client(
    app: FastAPI, user: dict[str, str], mock_analytics: MagicMock, mock_campaign: MagicMock
) -> TestClient:
    app.dependency_overrides[require_token] = lambda: user
    app.dependency_overrides[get_analytics_store] = lambda: mock_analytics
    app.dependency_overrides[get_campaign_store] = lambda: mock_campaign
    return TestClient(app)


# ---------------------------------------------------------------------------
# Intelligence endpoints
# ---------------------------------------------------------------------------


class TestIntelligenceResearcherAccess:
    """Researcher gets 403 on all intelligence detail / sub-detail endpoints."""

    def test_entity_detail_403(self, mock_analytics_store: MagicMock, mock_campaign_store: MagicMock) -> None:
        app = create_app()
        client = _build_client(app, RESEARCHER_USER, mock_analytics_store, mock_campaign_store)
        resp = client.get("/intelligence/entities/crypto_wallet/0xABC")
        assert resp.status_code == 403
        app.dependency_overrides.clear()

    def test_entity_activity_403(self, mock_analytics_store: MagicMock, mock_campaign_store: MagicMock) -> None:
        app = create_app()
        client = _build_client(app, RESEARCHER_USER, mock_analytics_store, mock_campaign_store)
        resp = client.get("/intelligence/entities/crypto_wallet/0xABC/activity")
        assert resp.status_code == 403
        app.dependency_overrides.clear()

    def test_entity_neighbors_403(self, mock_analytics_store: MagicMock, mock_campaign_store: MagicMock) -> None:
        app = create_app()
        client = _build_client(app, RESEARCHER_USER, mock_analytics_store, mock_campaign_store)
        resp = client.get("/intelligence/entities/crypto_wallet/0xABC/neighbors")
        assert resp.status_code == 403
        app.dependency_overrides.clear()

    def test_indicator_detail_403(self, mock_analytics_store: MagicMock, mock_campaign_store: MagicMock) -> None:
        app = create_app()
        client = _build_client(app, RESEARCHER_USER, mock_analytics_store, mock_campaign_store)
        resp = client.get("/intelligence/indicators/ind-001")
        assert resp.status_code == 403
        app.dependency_overrides.clear()

    def test_analyst_can_access_entity_detail(
        self, mock_analytics_store: MagicMock, mock_campaign_store: MagicMock
    ) -> None:
        """Analyst role must still get 200."""
        app = create_app()
        client = _build_client(app, ANALYST_USER, mock_analytics_store, mock_campaign_store)
        resp = client.get("/intelligence/entities/crypto_wallet/0xABC")
        assert resp.status_code == 200
        app.dependency_overrides.clear()

    def test_analyst_can_access_activity(self, mock_analytics_store: MagicMock, mock_campaign_store: MagicMock) -> None:
        app = create_app()
        client = _build_client(app, ANALYST_USER, mock_analytics_store, mock_campaign_store)
        resp = client.get("/intelligence/entities/crypto_wallet/0xABC/activity")
        assert resp.status_code == 200
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Case detail endpoint
# ---------------------------------------------------------------------------


class TestCaseResearcherAccess:
    """Researcher gets 403 on case detail."""

    def test_case_detail_403(self) -> None:
        app = create_app()
        app.dependency_overrides[require_token] = lambda: RESEARCHER_USER
        client = TestClient(app)
        resp = client.get("/cases/case-123")
        assert resp.status_code == 403
        app.dependency_overrides.clear()

    def test_case_detail_analyst_ok(self) -> None:
        """Analyst should get 404 (case doesn't exist), not 403."""
        app = create_app()
        app.dependency_overrides[require_token] = lambda: ANALYST_USER
        client = TestClient(app)
        resp = client.get("/cases/case-123")
        # 404 because mock case doesn't exist, but crucially NOT 403
        assert resp.status_code == 404
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Review detail endpoints
# ---------------------------------------------------------------------------


class TestReviewResearcherAccess:
    """Researcher gets 403 on all review detail endpoints."""

    def test_review_detail_403(self) -> None:
        app = create_app()
        app.dependency_overrides[require_token] = lambda: RESEARCHER_USER
        client = TestClient(app)
        resp = client.get("/reviews/review-abc")
        assert resp.status_code == 403
        app.dependency_overrides.clear()

    def test_reviews_by_case_403(self) -> None:
        app = create_app()
        app.dependency_overrides[require_token] = lambda: RESEARCHER_USER
        client = TestClient(app)
        resp = client.get("/reviews/case/case-123")
        assert resp.status_code == 403
        app.dependency_overrides.clear()

    def test_review_actions_403(self) -> None:
        app = create_app()
        app.dependency_overrides[require_token] = lambda: RESEARCHER_USER
        client = TestClient(app)
        resp = client.get("/reviews/review-abc/actions")
        assert resp.status_code == 403
        app.dependency_overrides.clear()
