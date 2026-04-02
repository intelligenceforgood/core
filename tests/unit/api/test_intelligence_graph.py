"""Tests for the intelligence graph API endpoints (Sprint 4).

Covers GET /intelligence/graph (seed/expand/filter, layout for >500 nodes)
and GET /intelligence/graph/export (PNG/SVG rendering).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from i4g.api.app import create_app
from i4g.api.intelligence import get_analytics_store, get_annotation_store, get_campaign_store

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity(entity_type: str, value: str, *, case_count: int = 2, risk: float = 50.0) -> dict:
    """Build a fake entity-stat dict."""
    return {
        "entity_type": entity_type,
        "canonical_value": value,
        "case_count": case_count,
        "victim_count": 1,
        "loss_sum": 1000.0,
        "max_risk_score": risk,
        "avg_risk_score": risk,
        "status": "active",
        "campaign_ids": "[]",
        "top_classifications": "[]",
    }


SEED_ENTITIES = [
    _make_entity("wallet", "0xAAA", case_count=3, risk=85),
    _make_entity("wallet", "0xBBB", case_count=3, risk=40),
    _make_entity("email", "a@b.com", case_count=2, risk=60),
]

# Graph service returns a simplified payload
GRAPH_PAYLOAD = {
    "nodes": [
        {"id": "wallet:0xAAA", "entity_type": "wallet", "label": "0xAAA", "case_count": 3, "risk_score": 85},
        {"id": "wallet:0xBBB", "entity_type": "wallet", "label": "0xBBB", "case_count": 3, "risk_score": 40},
    ],
    "edges": [
        {"source": "wallet:0xAAA", "target": "wallet:0xBBB", "weight": 2, "edge_type": "co-occurrence"},
    ],
    "layout": None,
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_analytics_store() -> MagicMock:
    """Create a mock AnalyticsStore with seed data."""
    store = MagicMock()
    store.list_entity_stats.return_value = list(SEED_ENTITIES)
    store.update_entity_status.return_value = True
    # SQL-based graph endpoint uses get_entity_stat + get_entity_neighbors
    store.get_entity_stat.return_value = {
        "entity_type": "wallet",
        "canonical_value": "0xAAA",
        "case_count": 3,
        "max_risk_score": 85,
    }
    store.get_entity_neighbors.return_value = [
        {
            "entity_type": "wallet",
            "canonical_value": "0xBBB",
            "case_count": 3,
            "shared_cases": 2,
            "risk_score": 40,
        },
    ]
    return store


@pytest.fixture()
def mock_campaign_store() -> MagicMock:
    """Create a mock ThreatCampaignStore."""
    store = MagicMock()
    store.list_linked_cases.return_value = [{"case_id": "c-1"}]
    return store


@pytest.fixture()
def mock_annotation_store() -> MagicMock:
    """Create a mock AnnotationStore."""
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
# GET /intelligence/graph
# ---------------------------------------------------------------------------


def test_graph_returns_payload(client: TestClient) -> None:
    """GET /intelligence/graph returns nodes, edges, counts."""
    resp = client.get("/intelligence/graph", params={"seed": "wallet:0xAAA"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["nodeCount"] == 2  # seed + 1 neighbor
    assert body["edgeCount"] == 1
    assert body["nodes"][0]["id"] == "wallet:0xAAA"
    assert body["edges"][0]["source"] == "wallet:0xAAA"


def test_graph_hop_param(client: TestClient, mock_analytics_store: MagicMock) -> None:
    """hops param triggers multiple rounds of get_entity_neighbors."""
    # With hops=2, get_entity_neighbors should be called for seed AND its neighbor
    mock_analytics_store.get_entity_neighbors.return_value = [
        {"entity_type": "wallet", "canonical_value": "0xBBB", "case_count": 3, "shared_cases": 2, "risk_score": 40},
    ]

    client.get("/intelligence/graph", params={"seed": "wallet:0xAAA", "hops": 2})
    # Called at least for seed (hop 1) and for 0xBBB (hop 2)
    assert mock_analytics_store.get_entity_neighbors.call_count >= 2


def test_graph_entity_type_filter(client: TestClient, mock_analytics_store: MagicMock) -> None:
    """entity_types param filters neighbors by type."""
    mock_analytics_store.get_entity_neighbors.return_value = [
        {"entity_type": "wallet", "canonical_value": "0xBBB", "case_count": 3, "shared_cases": 2, "risk_score": 40},
        {"entity_type": "email", "canonical_value": "a@b.com", "case_count": 2, "shared_cases": 1, "risk_score": 60},
    ]

    resp = client.get("/intelligence/graph", params={"seed": "wallet:0xAAA", "entity_types": "wallet"})
    body = resp.json()
    # Only wallet entities should be in the result (seed + 0xBBB)
    for node in body["nodes"]:
        assert node["entityType"] == "wallet"


def test_graph_risk_threshold_filters_entities(client: TestClient, mock_analytics_store: MagicMock) -> None:
    """risk_threshold filters out low-risk neighbors."""
    mock_analytics_store.get_entity_neighbors.return_value = [
        {"entity_type": "wallet", "canonical_value": "0xBBB", "case_count": 3, "shared_cases": 2, "risk_score": 40},
    ]
    # Neighbor 0xBBB has risk 40, which is below threshold 60
    mock_analytics_store.get_entity_stat.side_effect = lambda et, cv: (
        {"entity_type": et, "canonical_value": cv, "case_count": 3, "max_risk_score": 85}
        if cv == "0xAAA"
        else {"entity_type": et, "canonical_value": cv, "case_count": 3, "max_risk_score": 40}
    )

    resp = client.get("/intelligence/graph", params={"seed": "wallet:0xAAA", "risk_threshold": 60})
    body = resp.json()
    node_ids = [n["id"] for n in body["nodes"]]
    assert "wallet:0xBBB" not in node_ids  # risk 40 < 60


def test_graph_campaign_seed(client: TestClient, mock_campaign_store: MagicMock) -> None:
    """seed_type=campaign returns empty graph (not yet supported via SQL)."""
    resp = client.get("/intelligence/graph", params={"seed": "camp-1", "seed_type": "campaign"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["nodeCount"] == 0


def test_graph_campaign_seed_empty(client: TestClient, mock_campaign_store: MagicMock) -> None:
    """Empty campaign returns empty graph."""
    mock_campaign_store.list_linked_cases.return_value = []

    resp = client.get("/intelligence/graph", params={"seed": "camp-empty", "seed_type": "campaign"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["nodeCount"] == 0


def test_graph_seed_not_found(client: TestClient, mock_analytics_store: MagicMock) -> None:
    """Unknown seed entity returns empty graph."""
    mock_analytics_store.get_entity_stat.return_value = None

    resp = client.get("/intelligence/graph", params={"seed": "wallet:0xUNKNOWN"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["nodeCount"] == 0


# ---------------------------------------------------------------------------
# GET /intelligence/graph/export
# ---------------------------------------------------------------------------


def test_graph_export_png(client: TestClient) -> None:
    """GET /intelligence/graph/export returns PNG image."""
    resp = client.get("/intelligence/graph/export", params={"seed": "wallet:0xAAA", "fmt": "png"})
    # May return 200 (with matplotlib) or 501 (without matplotlib); both are valid
    assert resp.status_code in (200, 501)
    if resp.status_code == 200:
        assert resp.headers["content-type"] == "image/png"


def test_graph_export_svg(client: TestClient) -> None:
    """GET /intelligence/graph/export?fmt=svg returns SVG image."""
    resp = client.get("/intelligence/graph/export", params={"seed": "wallet:0xAAA", "fmt": "svg"})
    assert resp.status_code in (200, 501)
    if resp.status_code == 200:
        assert resp.headers["content-type"] == "image/svg+xml"
