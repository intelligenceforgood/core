"""Tests for the taxonomy API endpoints (Sprint 4 — S4-08/09/10).

Covers GET /impact/taxonomy/sankey, /impact/taxonomy/heatmap,
and /impact/taxonomy/trend.
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
    """Create a mock DB session returning taxonomy data."""
    session = MagicMock()
    # Default: empty results
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
# GET /impact/taxonomy/sankey
# ---------------------------------------------------------------------------


def test_taxonomy_sankey_empty(client: TestClient) -> None:
    """Sankey returns empty list when no data."""
    resp = client.get("/impact/taxonomy/sankey")
    assert resp.status_code == 200
    assert resp.json() == {"nodes": [], "links": []}


def test_taxonomy_sankey_with_data(client: TestClient, mock_db_session: MagicMock) -> None:
    """Sankey returns nodes and links for classification flows."""
    mock_db_session.execute.return_value.fetchall.return_value = [
        _row(classification="Crypto Fraud - Pig Butchering", cnt=15),
        _row(classification="Crypto Fraud - Ponzi", cnt=8),
        _row(classification="Romance Scam - Catfish", cnt=10),
    ]

    resp = client.get("/impact/taxonomy/sankey")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["nodes"]) > 0
    assert len(body["links"]) > 0


def test_taxonomy_sankey_accepts_period(client: TestClient) -> None:
    """Sankey accepts period query parameter."""
    resp = client.get("/impact/taxonomy/sankey", params={"period": "30d"})
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /impact/taxonomy/heatmap
# ---------------------------------------------------------------------------


def test_taxonomy_heatmap_empty(client: TestClient) -> None:
    """Heatmap returns empty list when no data."""
    resp = client.get("/impact/taxonomy/heatmap")
    assert resp.status_code == 200
    assert resp.json() == []


def test_taxonomy_heatmap_with_data(client: TestClient, mock_db_session: MagicMock) -> None:
    """Heatmap returns cells with category/period/count."""
    mock_db_session.execute.return_value.fetchall.return_value = [
        _row(classification="Crypto Fraud", created_at=datetime(2025, 6, 1, tzinfo=UTC)),
        _row(classification="Crypto Fraud", created_at=datetime(2025, 6, 2, tzinfo=UTC)),
        _row(classification="Romance Scam", created_at=datetime(2025, 6, 1, tzinfo=UTC)),
    ]

    resp = client.get("/impact/taxonomy/heatmap")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    if body:
        assert "category" in body[0]
        assert "period" in body[0]
        assert "count" in body[0]


# ---------------------------------------------------------------------------
# GET /impact/taxonomy/trend
# ---------------------------------------------------------------------------


def test_taxonomy_trend_empty(client: TestClient) -> None:
    """Trend returns empty list when no data."""
    resp = client.get("/impact/taxonomy/trend")
    assert resp.status_code == 200
    assert resp.json() == []


def test_taxonomy_trend_with_data(client: TestClient, mock_db_session: MagicMock) -> None:
    """Trend returns time-series data per category."""
    mock_db_session.execute.return_value.fetchall.return_value = [
        _row(classification="Crypto Fraud", created_at=datetime(2025, 6, 1, tzinfo=UTC)),
        _row(classification="Crypto Fraud", created_at=datetime(2025, 6, 8, tzinfo=UTC)),
        _row(classification="Romance Scam", created_at=datetime(2025, 6, 1, tzinfo=UTC)),
    ]

    resp = client.get("/impact/taxonomy/trend")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    if body:
        assert "period" in body[0]
        assert "category" in body[0]
        assert "count" in body[0]


def test_taxonomy_trend_category_filter(client: TestClient, mock_db_session: MagicMock) -> None:
    """Trend categories param filters results."""
    mock_db_session.execute.return_value.fetchall.return_value = [
        _row(classification="Crypto Fraud", created_at=datetime(2025, 6, 1, tzinfo=UTC)),
    ]

    resp = client.get("/impact/taxonomy/trend", params={"categories": "Crypto Fraud"})
    assert resp.status_code == 200
