"""Tests for the intelligence API endpoints.

Covers entity list/detail, indicator list/detail, dashboard widgets,
entity activity sparklines, entity neighbors, and search facets.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from i4g.api.app import create_app
from i4g.api.intelligence import get_analytics_store, get_campaign_store

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SAMPLE_ENTITIES = [
    {
        "entity_type": "crypto_wallet",
        "canonical_value": "0xABCDEF1234567890",
        "case_count": 5,
        "first_seen_at": "2025-01-01",
        "last_active_at": "2025-06-01",
        "loss_sum": 150000.0,
        "risk_score": 0.85,
        "status": "active",
        "case_ids": ["c1", "c2"],
        "campaign_ids": ["camp-1"],
    },
    {
        "entity_type": "bank_account",
        "canonical_value": "1234567890",
        "case_count": 2,
        "first_seen_at": "2025-03-01",
        "last_active_at": "2025-05-01",
        "loss_sum": 45000.0,
        "risk_score": 0.45,
        "status": "dormant",
        "case_ids": ["c3"],
        "campaign_ids": [],
    },
]

_SAMPLE_INDICATORS = [
    {
        "indicator_id": "ind-001",
        "indicator_value": "192.168.1.1",
        "category": "ip",
        "case_count": 3,
        "loss_sum": 50000.0,
    },
    {
        "indicator_id": "ind-002",
        "indicator_value": "9876543210",
        "category": "bank",
        "case_count": 7,
        "loss_sum": 200000.0,
    },
]


@pytest.fixture()
def mock_analytics_store() -> MagicMock:
    """Create a mock AnalyticsStore."""
    store = MagicMock()
    store.list_entity_stats.return_value = list(_SAMPLE_ENTITIES)
    store.count_entity_stats.return_value = len(_SAMPLE_ENTITIES)
    store.get_entity_stat.return_value = dict(_SAMPLE_ENTITIES[0])
    store.list_indicator_stats.return_value = list(_SAMPLE_INDICATORS)
    store.count_indicator_stats.return_value = len(_SAMPLE_INDICATORS)
    store.get_indicator_stat.return_value = dict(_SAMPLE_INDICATORS[0])
    store.get_entity_activity.return_value = [
        {"week": "2025-W01", "case_count": 1},
        {"week": "2025-W02", "case_count": 3},
    ]
    store.get_entity_neighbors.return_value = [
        {"entity_type": "bank_account", "canonical_value": "999888", "case_count": 2, "shared_cases": 2},
    ]
    store.get_latest_kpi.return_value = {
        "new_indicators": 12,
        "proactive_cases": 5,
        "reactive_cases": 8,
    }
    store.list_platform_kpis.return_value = [
        {"period_start": "2025-W01", "total_loss": 10000.0},
        {"period_start": "2025-W02", "total_loss": 15000.0},
    ]
    return store


@pytest.fixture()
def mock_campaign_store() -> MagicMock:
    """Create a mock ThreatCampaignStore."""
    store = MagicMock()
    store.get_campaign.return_value = {"name": "Pig Butchering Ring"}
    store.list_campaigns.return_value = [{"id": "camp-1", "name": "Emerging A"}]
    return store


@pytest.fixture()
def client(mock_analytics_store, mock_campaign_store) -> TestClient:
    """Create a TestClient with mocked stores."""
    app = create_app()
    app.dependency_overrides[get_analytics_store] = lambda: mock_analytics_store
    app.dependency_overrides[get_campaign_store] = lambda: mock_campaign_store
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Entity list
# ---------------------------------------------------------------------------


def test_list_entities_returns_items(client: TestClient, mock_analytics_store: MagicMock) -> None:
    """GET /intelligence/entities returns paginated entity list."""
    resp = client.get("/intelligence/entities")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    assert body["items"][0]["entityType"] == "crypto_wallet"
    mock_analytics_store.list_entity_stats.assert_called_once()


def test_list_entities_passes_filters(client: TestClient, mock_analytics_store: MagicMock) -> None:
    """Query params are forwarded to the store."""
    client.get(
        "/intelligence/entities",
        params={"entity_type": "bank_account", "status": "dormant", "min_case_count": 1, "limit": 10, "offset": 5},
    )
    call_kwargs = mock_analytics_store.list_entity_stats.call_args.kwargs
    assert call_kwargs["entity_type"] == "bank_account"
    assert call_kwargs["status"] == "dormant"
    assert call_kwargs["min_case_count"] == 1
    assert call_kwargs["limit"] == 10
    assert call_kwargs["offset"] == 5


# ---------------------------------------------------------------------------
# Entity detail
# ---------------------------------------------------------------------------


def test_get_entity_returns_detail(client: TestClient) -> None:
    """GET /intelligence/entities/{type}/{value} returns entity with campaigns."""
    resp = client.get("/intelligence/entities/crypto_wallet/0xABCDEF1234567890")
    assert resp.status_code == 200
    body = resp.json()
    assert body["entityType"] == "crypto_wallet"
    assert body["campaigns"][0]["name"] == "Pig Butchering Ring"


def test_get_entity_not_found(client: TestClient, mock_analytics_store: MagicMock) -> None:
    """404 when entity is missing."""
    mock_analytics_store.get_entity_stat.return_value = None
    resp = client.get("/intelligence/entities/crypto_wallet/nonexistent")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Entity activity sparkline
# ---------------------------------------------------------------------------


def test_get_entity_activity(client: TestClient) -> None:
    """GET /intelligence/entities/{type}/{value}/activity returns weekly data."""
    resp = client.get("/intelligence/entities/crypto_wallet/0xABCDEF1234567890/activity")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert body[0]["week"] == "2025-W01"  # single-word keys stay the same


def test_get_entity_activity_not_found(client: TestClient, mock_analytics_store: MagicMock) -> None:
    """404 when entity is missing for activity."""
    mock_analytics_store.get_entity_stat.return_value = None
    resp = client.get("/intelligence/entities/crypto_wallet/gone/activity")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Entity neighbors
# ---------------------------------------------------------------------------


def test_get_entity_neighbors(client: TestClient) -> None:
    """GET /intelligence/entities/{type}/{value}/neighbors returns graph."""
    resp = client.get("/intelligence/entities/crypto_wallet/0xABCDEF1234567890/neighbors")
    assert resp.status_code == 200
    body = resp.json()
    assert body["seed"] == "crypto_wallet:0xABCDEF1234567890"
    assert len(body["nodes"]) == 2  # seed + 1 neighbor
    assert len(body["edges"]) == 1


def test_get_entity_neighbors_not_found(client: TestClient, mock_analytics_store: MagicMock) -> None:
    """404 when entity is missing for neighbors."""
    mock_analytics_store.get_entity_stat.return_value = None
    resp = client.get("/intelligence/entities/crypto_wallet/gone/neighbors")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Entity cases
# ---------------------------------------------------------------------------


def test_get_entity_cases_not_found(client: TestClient, mock_analytics_store: MagicMock) -> None:
    """404 when entity doesn't exist for cases lookup."""
    mock_analytics_store.get_entity_stat.return_value = None
    resp = client.get("/intelligence/entities/crypto_wallet/gone/cases")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Indicator list
# ---------------------------------------------------------------------------


def test_list_indicators(client: TestClient, mock_analytics_store: MagicMock) -> None:
    """GET /intelligence/indicators returns paginated indicator list."""
    resp = client.get("/intelligence/indicators")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    mock_analytics_store.list_indicator_stats.assert_called_once()


def test_list_indicators_category_filter(client: TestClient, mock_analytics_store: MagicMock) -> None:
    """Category param is forwarded to the store."""
    client.get("/intelligence/indicators", params={"category": "crypto"})
    call_kwargs = mock_analytics_store.list_indicator_stats.call_args.kwargs
    assert call_kwargs["category"] == "crypto"


# ---------------------------------------------------------------------------
# Indicator detail
# ---------------------------------------------------------------------------


def test_get_indicator(client: TestClient) -> None:
    """GET /intelligence/indicators/{id} returns indicator stats."""
    resp = client.get("/intelligence/indicators/ind-001")
    assert resp.status_code == 200
    body = resp.json()
    assert body["indicatorId"] == "ind-001"


def test_get_indicator_not_found(client: TestClient, mock_analytics_store: MagicMock) -> None:
    """404 when indicator is missing."""
    mock_analytics_store.get_indicator_stat.return_value = None
    resp = client.get("/intelligence/indicators/missing")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Dashboard widgets
# ---------------------------------------------------------------------------


def test_dashboard_widgets(client: TestClient, mock_analytics_store: MagicMock) -> None:
    """GET /intelligence/dashboard returns widget data."""
    resp = client.get("/intelligence/dashboard")
    assert resp.status_code == 200
    body = resp.json()
    assert "activeThreats" in body
    assert body["newIndicators"] == 12
    assert body["emergingCampaigns"] == 1
    assert len(body["lossTrend"]) == 2
    assert len(body["sourceBreakdown"]) == 2


# ---------------------------------------------------------------------------
# Search facets
# ---------------------------------------------------------------------------


def test_search_facets(client: TestClient, mock_analytics_store: MagicMock) -> None:
    """GET /intelligence/search/facets returns type/category counts."""
    resp = client.get("/intelligence/search/facets")
    assert resp.status_code == 200
    body = resp.json()
    assert "entity_types" in body
    assert "indicator_categories" in body
    # 2 entity types from sample data
    assert len(body["entity_types"]) == 2
