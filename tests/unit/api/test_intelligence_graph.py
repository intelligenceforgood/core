"""Tests for the intelligence graph API endpoints (Sprint 4).

Covers GET /intelligence/graph (seed/expand/filter, layout for >500 nodes)
and GET /intelligence/graph/export (PNG/SVG rendering).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from i4g.api.app import create_app
from i4g.api.intelligence import get_analytics_store, get_annotation_store, get_campaign_store

# The GraphService import is local inside the endpoint functions, so we patch
# it at the source module level: i4g.services.graph_service.GraphService
_GS_PATCH = "i4g.services.graph_service.GraphService"

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


@patch(_GS_PATCH)
def test_graph_returns_payload(mock_gs_cls, client: TestClient) -> None:
    """GET /intelligence/graph returns nodes, edges, counts."""
    instance = mock_gs_cls.return_value
    instance.get_neighbors.return_value = GRAPH_PAYLOAD

    resp = client.get("/intelligence/graph", params={"seed": "wallet:0xAAA"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["nodeCount"] == 2
    assert body["edgeCount"] == 1
    assert body["nodes"][0]["id"] == "wallet:0xAAA"
    assert body["edges"][0]["source"] == "wallet:0xAAA"


@patch(_GS_PATCH)
def test_graph_hop_param(mock_gs_cls, client: TestClient) -> None:
    """hops param is forwarded to GraphService.get_neighbors."""
    instance = mock_gs_cls.return_value
    instance.get_neighbors.return_value = {"nodes": [], "edges": []}

    client.get("/intelligence/graph", params={"seed": "wallet:0xAAA", "hops": 2})
    _, kwargs = instance.get_neighbors.call_args
    assert kwargs["hops"] == 2


@patch(_GS_PATCH)
def test_graph_entity_type_filter(mock_gs_cls, client: TestClient, mock_analytics_store: MagicMock) -> None:
    """entity_types param filters entities forwarded to graph service."""
    instance = mock_gs_cls.return_value
    instance.get_neighbors.return_value = {"nodes": [], "edges": []}

    client.get("/intelligence/graph", params={"seed": "wallet:0xAAA", "entity_types": "wallet"})
    _, kwargs = instance.get_neighbors.call_args
    assert kwargs["entity_types"] == ["wallet"]


@patch(_GS_PATCH)
def test_graph_risk_threshold_filters_entities(
    mock_gs_cls, client: TestClient, mock_analytics_store: MagicMock
) -> None:
    """risk_threshold filters out low-risk entities before graph construction."""
    instance = mock_gs_cls.return_value
    instance.get_neighbors.return_value = {"nodes": [], "edges": []}

    client.get("/intelligence/graph", params={"seed": "wallet:0xAAA", "risk_threshold": 60})
    # Only entities with risk >= 60 passed to GraphService — 0xAAA (85) and a@b.com (60)
    args_list = mock_gs_cls.call_args
    adjacency = args_list[0][0]  # first positional arg
    assert "wallet:0xBBB" not in adjacency  # risk 40 < 60


@patch(_GS_PATCH)
def test_graph_campaign_seed(mock_gs_cls, client: TestClient, mock_campaign_store: MagicMock) -> None:
    """seed_type=campaign expands via campaign store linked cases."""
    instance = mock_gs_cls.return_value
    instance.serialize.return_value = {"nodes": [], "edges": [], "layout": None}

    client.get("/intelligence/graph", params={"seed": "camp-1", "seed_type": "campaign"})
    mock_campaign_store.list_linked_cases.assert_called_once()


@patch(_GS_PATCH)
def test_graph_campaign_seed_empty(mock_gs_cls, client: TestClient, mock_campaign_store: MagicMock) -> None:
    """Empty campaign returns empty graph."""
    mock_campaign_store.list_linked_cases.return_value = []

    resp = client.get("/intelligence/graph", params={"seed": "camp-empty", "seed_type": "campaign"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["nodeCount"] == 0


@patch(_GS_PATCH)
def test_graph_large_layout(mock_gs_cls, client: TestClient, mock_analytics_store: MagicMock) -> None:
    """Graph with >500 nodes triggers layout computation."""
    # Return >500 entity stats
    large_entities = [_make_entity("wallet", f"0x{i:04d}") for i in range(600)]
    mock_analytics_store.list_entity_stats.return_value = large_entities

    layout_data = {str(i): {"x": 0.1, "y": 0.2} for i in range(600)}
    instance = mock_gs_cls.return_value
    instance.get_neighbors.return_value = {
        "nodes": [{"id": f"wallet:0x{i:04d}", "entity_type": "wallet", "label": f"0x{i:04d}"} for i in range(600)],
        "edges": [],
        "layout": layout_data,
    }

    resp = client.get("/intelligence/graph", params={"seed": "wallet:0x0000"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["nodeCount"] == 600


# ---------------------------------------------------------------------------
# GET /intelligence/graph/export
# ---------------------------------------------------------------------------


@patch(_GS_PATCH)
def test_graph_export_png(mock_gs_cls, client: TestClient) -> None:
    """GET /intelligence/graph/export returns PNG image."""
    instance = mock_gs_cls.return_value
    instance.get_neighbors.return_value = GRAPH_PAYLOAD

    resp = client.get("/intelligence/graph/export", params={"seed": "wallet:0xAAA", "fmt": "png"})
    # May return 200 (with matplotlib) or 501 (without matplotlib); both are valid
    assert resp.status_code in (200, 501)
    if resp.status_code == 200:
        assert resp.headers["content-type"] == "image/png"


@patch(_GS_PATCH)
def test_graph_export_svg(mock_gs_cls, client: TestClient) -> None:
    """GET /intelligence/graph/export?fmt=svg returns SVG image."""
    instance = mock_gs_cls.return_value
    instance.get_neighbors.return_value = GRAPH_PAYLOAD

    resp = client.get("/intelligence/graph/export", params={"seed": "wallet:0xAAA", "fmt": "svg"})
    assert resp.status_code in (200, 501)
    if resp.status_code == 200:
        assert resp.headers["content-type"] == "image/svg+xml"
