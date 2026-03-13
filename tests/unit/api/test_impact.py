"""Tests for the Impact Analytics API endpoints.

Covers /impact/dashboard, /impact/loss-by-taxonomy,
/impact/detection-velocity, /impact/pipeline-funnel,
and /impact/cumulative-indicators.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from i4g.api.app import create_app
from i4g.api.auth import require_token
from i4g.api.impact import _get_analytics_store
from i4g.api.review_deps import get_db_session

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_analytics_store() -> MagicMock:
    """Create a mock AnalyticsStore."""
    store = MagicMock()
    store.list_platform_kpis.return_value = [
        {
            "period_type": "monthly",
            "period_start": "2025-06-01",
            "total_cases": 100,
            "proactive_cases": 60,
            "reactive_cases": 40,
            "total_loss": 500000.0,
            "new_indicators": 25,
            "new_entities": 10,
            "site_scans": 15,
            "ecx_submissions": 5,
            "cases_actioned": 80,
            "median_action_hours": 12.5,
        },
    ]
    return store


@pytest.fixture()
def mock_db_session() -> MagicMock:
    """Create a mock database session."""
    session = MagicMock()
    # scalar() returns 0 by default (used for counts/sums)
    session.scalar.return_value = 0
    # execute().all() returns empty list (used for row queries)
    session.execute.return_value.all.return_value = []
    session.execute.return_value.fetchall.return_value = []
    session.execute.return_value.fetchone.return_value = None
    return session


@pytest.fixture()
def client(mock_analytics_store, mock_db_session) -> TestClient:
    """Create a TestClient with mocked dependencies."""
    app = create_app()
    app.dependency_overrides[require_token] = lambda: {"username": "analyst@test.io", "role": "analyst"}
    app.dependency_overrides[_get_analytics_store] = lambda: mock_analytics_store
    app.dependency_overrides[get_db_session] = lambda: mock_db_session
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


def test_dashboard_returns_kpis(client: TestClient) -> None:
    """GET /impact/dashboard returns KPI cards."""
    resp = client.get("/impact/dashboard")
    assert resp.status_code == 200
    body = resp.json()
    assert "kpis" in body
    assert "periodLabel" in body
    assert isinstance(body["kpis"], list)


def test_dashboard_accepts_period_param(client: TestClient) -> None:
    """GET /impact/dashboard?period=7d accepts period parameter."""
    resp = client.get("/impact/dashboard", params={"period": "7d"})
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Loss by Taxonomy
# ---------------------------------------------------------------------------


def test_loss_by_taxonomy_returns_list(client: TestClient) -> None:
    """GET /impact/loss-by-taxonomy returns a list."""
    resp = client.get("/impact/loss-by-taxonomy")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)


# ---------------------------------------------------------------------------
# Detection Velocity
# ---------------------------------------------------------------------------


def test_detection_velocity_returns_list(client: TestClient) -> None:
    """GET /impact/detection-velocity returns data points."""
    resp = client.get("/impact/detection-velocity")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)


# ---------------------------------------------------------------------------
# Pipeline Funnel
# ---------------------------------------------------------------------------


def test_pipeline_funnel_returns_stages(client: TestClient) -> None:
    """GET /impact/pipeline-funnel returns funnel stages."""
    resp = client.get("/impact/pipeline-funnel")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)


# ---------------------------------------------------------------------------
# Cumulative Indicators
# ---------------------------------------------------------------------------


def test_cumulative_indicators_returns_list(client: TestClient) -> None:
    """GET /impact/cumulative-indicators returns data points."""
    resp = client.get("/impact/cumulative-indicators")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
