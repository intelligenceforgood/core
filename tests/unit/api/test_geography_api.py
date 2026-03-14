"""Tests for the geography API endpoints (Sprint 4 — S4-11/12).

Covers GET /impact/geography and GET /impact/geography/{country}.
"""

from __future__ import annotations

from datetime import UTC, datetime
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


def _row(**kwargs):
    """Create a SimpleNamespace that behaves like an SA row."""
    from types import SimpleNamespace

    return SimpleNamespace(**kwargs)


@pytest.fixture()
def mock_analytics_store() -> MagicMock:
    """Create a mock AnalyticsStore."""
    store = MagicMock()
    store.list_platform_kpis.return_value = []
    return store


@pytest.fixture()
def mock_db_session() -> MagicMock:
    """Create a mock DB session."""
    session = MagicMock()
    session.scalar.return_value = 0
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
# GET /impact/geography
# ---------------------------------------------------------------------------


def test_geography_summary_empty(client: TestClient) -> None:
    """Geography summary returns empty list when no data."""
    resp = client.get("/impact/geography")
    assert resp.status_code == 200
    assert resp.json() == []


def test_geography_summary_with_data(client: TestClient, mock_db_session: MagicMock) -> None:
    """Geography summary returns country aggregations."""
    mock_db_session.execute.return_value.fetchall.return_value = [
        _row(victim_country="US", case_count=50, total_loss=250000),
        _row(victim_country="GB", case_count=20, total_loss=80000),
        _row(victim_country="AU", case_count=10, total_loss=35000),
    ]

    resp = client.get("/impact/geography")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 3
    assert body[0]["country"] == "US"
    assert body[0]["caseCount"] == 50
    assert body[0]["totalLoss"] == 250000.0


def test_geography_summary_accepts_period(client: TestClient) -> None:
    """Geography summary accepts period query parameter."""
    resp = client.get("/impact/geography", params={"period": "30d"})
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /impact/geography/{country}
# ---------------------------------------------------------------------------


def test_geography_detail_empty(client: TestClient) -> None:
    """Country detail returns empty records when no matching data."""
    resp = client.get("/impact/geography/US")
    assert resp.status_code == 200
    body = resp.json()
    assert body["country"] == "US"
    assert body["totalCases"] == 0
    assert body["records"] == []


def test_geography_detail_with_records(client: TestClient, mock_db_session: MagicMock) -> None:
    """Country detail returns individual case records."""
    mock_db_session.execute.return_value.fetchall.return_value = [
        _row(
            case_id="c-001",
            classification="Crypto Fraud",
            loss_amount=15000,
            created_at=datetime(2025, 6, 1, tzinfo=UTC),
        ),
        _row(
            case_id="c-002",
            classification="Romance Scam",
            loss_amount=8000,
            created_at=datetime(2025, 6, 5, tzinfo=UTC),
        ),
    ]

    resp = client.get("/impact/geography/US")
    assert resp.status_code == 200
    body = resp.json()
    assert body["country"] == "US"
    assert body["totalCases"] == 2
    assert body["totalLoss"] == 23000.0
    assert len(body["records"]) == 2
    assert body["records"][0]["caseId"] == "c-001"


def test_geography_detail_accepts_limit(client: TestClient) -> None:
    """Country detail accepts limit query parameter."""
    resp = client.get("/impact/geography/US", params={"limit": 10})
    assert resp.status_code == 200


def test_geography_detail_accepts_period(client: TestClient) -> None:
    """Country detail accepts period query parameter."""
    resp = client.get("/impact/geography/US", params={"period": "7d"})
    assert resp.status_code == 200
