"""Tests for the intelligence timeline API endpoint (Sprint 4 — S4-13).

Covers GET /intelligence/timeline with period presets and granularity options.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from i4g.api.app import create_app
from i4g.api.intelligence import get_analytics_store, get_annotation_store, get_campaign_store

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

_WEEKLY_KPIS = [
    {"period_start": "2025-W01", "total_cases": 10, "new_indicators": 5},
    {"period_start": "2025-W02", "total_cases": 14, "new_indicators": 8},
    {"period_start": "2025-W03", "total_cases": 7, "new_indicators": 3},
]

_MONTHLY_KPIS = [
    {"period_start": "2025-01", "total_cases": 31, "new_indicators": 16},
    {"period_start": "2025-02", "total_cases": 28, "new_indicators": 12},
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_analytics_store() -> MagicMock:
    """Create a mock AnalyticsStore returning timeline KPIs."""
    store = MagicMock()
    store.list_platform_kpis.return_value = list(_WEEKLY_KPIS)
    return store


@pytest.fixture()
def mock_campaign_store() -> MagicMock:
    """Create a noop ThreatCampaignStore mock."""
    return MagicMock()


@pytest.fixture()
def mock_annotation_store() -> MagicMock:
    """Create a noop AnnotationStore mock."""
    return MagicMock()


@pytest.fixture()
def client(mock_analytics_store, mock_campaign_store, mock_annotation_store) -> TestClient:
    """Create a TestClient with mocked stores."""
    app = create_app()
    app.dependency_overrides[get_analytics_store] = lambda: mock_analytics_store
    app.dependency_overrides[get_campaign_store] = lambda: mock_campaign_store
    app.dependency_overrides[get_annotation_store] = lambda: mock_annotation_store
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Timeline tests
# ---------------------------------------------------------------------------


def test_timeline_returns_tracks(client: TestClient) -> None:
    """GET /intelligence/timeline returns cases and indicators tracks."""
    resp = client.get("/intelligence/timeline")
    assert resp.status_code == 200
    body = resp.json()
    assert "tracks" in body
    assert len(body["tracks"]) == 2
    track_names = {t["track"] for t in body["tracks"]}
    assert track_names == {"cases", "indicators"}


def test_timeline_default_granularity(client: TestClient) -> None:
    """Default granularity is 'week'."""
    resp = client.get("/intelligence/timeline")
    assert resp.json()["granularity"] == "week"


def test_timeline_monthly_granularity(client: TestClient, mock_analytics_store: MagicMock) -> None:
    """granularity=month maps to 'monthly' period_type."""
    mock_analytics_store.list_platform_kpis.return_value = list(_MONTHLY_KPIS)
    resp = client.get("/intelligence/timeline", params={"granularity": "month"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["granularity"] == "month"
    # Verify store was called with monthly period_type
    call_kwargs = mock_analytics_store.list_platform_kpis.call_args.kwargs
    assert call_kwargs["period_type"] == "monthly"


def test_timeline_period_7d(client: TestClient, mock_analytics_store: MagicMock) -> None:
    """period=7d limits date range to last 7 days."""
    client.get("/intelligence/timeline", params={"period": "7d"})
    call_kwargs = mock_analytics_store.list_platform_kpis.call_args.kwargs
    start = call_kwargs["start_date"]
    end = call_kwargs["end_date"]
    assert (end - start).days == 7


def test_timeline_period_year(client: TestClient, mock_analytics_store: MagicMock) -> None:
    """period=year limits date range to 365 days."""
    client.get("/intelligence/timeline", params={"period": "year"})
    call_kwargs = mock_analytics_store.list_platform_kpis.call_args.kwargs
    start = call_kwargs["start_date"]
    end = call_kwargs["end_date"]
    assert (end - start).days == 365


def test_timeline_tracks_contain_data(client: TestClient) -> None:
    """Each track has data points with period and count keys."""
    resp = client.get("/intelligence/timeline")
    body = resp.json()
    cases_track = next(t for t in body["tracks"] if t["track"] == "cases")
    assert len(cases_track["data"]) == 3
    assert cases_track["data"][0]["period"] == "2025-W01"
    assert cases_track["data"][0]["count"] == 10

    indicators_track = next(t for t in body["tracks"] if t["track"] == "indicators")
    assert indicators_track["data"][0]["count"] == 5
