"""Tests for the GraphService — entity co-occurrence network analysis.

Covers graph construction, get_neighbors, get_subgraph, detect_clusters,
compute_layout, and serialize.
"""

from __future__ import annotations

import pytest

from i4g.services.graph_service import GraphEdge, GraphNode, GraphService

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

_ADJACENCY = {
    "wallet:W1": ["case-1", "case-2"],
    "wallet:W2": ["case-1", "case-3"],
    "bank:B1": ["case-2", "case-3"],
    "ip:I1": ["case-1"],
    "domain:D1": ["case-4"],  # isolated from the main cluster via case-4
}

_META = {
    "wallet:W1": {"entity_type": "wallet", "label": "W1", "case_count": 2, "risk_score": 0.9},
    "wallet:W2": {"entity_type": "wallet", "label": "W2", "case_count": 2, "risk_score": 0.7},
    "bank:B1": {"entity_type": "bank", "label": "B1", "case_count": 2, "risk_score": 0.5},
    "ip:I1": {"entity_type": "ip", "label": "I1", "case_count": 1, "risk_score": 0.3},
    "domain:D1": {"entity_type": "domain", "label": "D1", "case_count": 1, "risk_score": 0.2},
}


@pytest.fixture()
def svc() -> GraphService:
    """Build a GraphService from sample adjacency."""
    return GraphService(_ADJACENCY, entity_meta=_META)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_graph_has_correct_node_count(svc: GraphService) -> None:
    """All entity IDs become graph nodes."""
    payload = svc.serialize()
    assert payload["node_count"] == 5


def test_graph_edges_are_co_occurrences(svc: GraphService) -> None:
    """Edges exist between entities sharing at least one case."""
    payload = svc.serialize()
    edge_pairs = {(e["source"], e["target"]) for e in payload["edges"]}
    # W1 & W2 share case-1  →  edge exists (either direction)
    assert ("wallet:W1", "wallet:W2") in edge_pairs or ("wallet:W2", "wallet:W1") in edge_pairs
    # D1 only in case-4 alone  →  no edge to others
    assert not any("domain:D1" in pair for pair in edge_pairs)


# ---------------------------------------------------------------------------
# get_neighbors
# ---------------------------------------------------------------------------


def test_get_neighbors_1_hop(svc: GraphService) -> None:
    """1-hop neighbors of W1 include W2, B1, I1 (share case-1 or case-2)."""
    result = svc.get_neighbors("wallet:W1", hops=1)
    node_ids = {n["id"] for n in result["nodes"]}
    assert "wallet:W1" in node_ids  # seed always present
    assert "wallet:W2" in node_ids
    assert "bank:B1" in node_ids
    assert "ip:I1" in node_ids
    # D1 is not reachable in 1 hop
    assert "domain:D1" not in node_ids


def test_get_neighbors_missing_seed(svc: GraphService) -> None:
    """Missing seed returns empty result."""
    result = svc.get_neighbors("nonexistent:X")
    assert result["nodes"] == []
    assert result["edges"] == []


def test_get_neighbors_type_filter(svc: GraphService) -> None:
    """Entity type filter restricts neighbor types."""
    result = svc.get_neighbors("wallet:W1", hops=1, entity_types=["bank"])
    non_seed = [n for n in result["nodes"] if n["id"] != "wallet:W1"]
    assert all(n["entity_type"] == "bank" for n in non_seed)


# ---------------------------------------------------------------------------
# get_subgraph
# ---------------------------------------------------------------------------


def test_get_subgraph(svc: GraphService) -> None:
    """Subgraph contains only requested nodes and edges between them."""
    result = svc.get_subgraph(["wallet:W1", "wallet:W2"])
    node_ids = {n["id"] for n in result["nodes"]}
    assert node_ids == {"wallet:W1", "wallet:W2"}
    assert len(result["edges"]) == 1


def test_get_subgraph_excludes_invalid_ids(svc: GraphService) -> None:
    """Invalid node IDs are silently ignored."""
    result = svc.get_subgraph(["wallet:W1", "fake:X"])
    assert len(result["nodes"]) == 1


def test_get_subgraph_no_edges(svc: GraphService) -> None:
    """Can request nodes without edges."""
    result = svc.get_subgraph(["wallet:W1", "wallet:W2"], include_edges=False)
    assert result["edges"] == []


# ---------------------------------------------------------------------------
# detect_clusters
# ---------------------------------------------------------------------------


def test_detect_clusters_default_min_size(svc: GraphService) -> None:
    """At least one cluster of size >= 3 exists (W1, W2, B1, I1 share cases)."""
    clusters = svc.detect_clusters(min_size=3)
    assert len(clusters) >= 1
    sizes = [c["size"] for c in clusters]
    assert max(sizes) >= 3


def test_detect_clusters_high_min_excludes_small(svc: GraphService) -> None:
    """High min_size can exclude all clusters."""
    clusters = svc.detect_clusters(min_size=100)
    assert clusters == []


# ---------------------------------------------------------------------------
# compute_layout
# ---------------------------------------------------------------------------


def test_compute_layout_small_graph(svc: GraphService) -> None:
    """Small graphs (< 500 nodes) return empty layout (not needed)."""
    layout = svc.compute_layout()
    assert layout == {}


def test_compute_layout_large_graph() -> None:
    """Graphs with >= 500 nodes get pre-computed positions."""
    # Build adjacency with 550 entities sharing one case
    adj = {f"e:{i}": ["case-big"] for i in range(550)}
    big_svc = GraphService(adj)
    layout = big_svc.compute_layout()
    assert len(layout) == 550
    first = next(iter(layout.values()))
    assert "x" in first and "y" in first


# ---------------------------------------------------------------------------
# serialize
# ---------------------------------------------------------------------------


def test_serialize_contains_counts(svc: GraphService) -> None:
    """Serialized payload has node_count and edge_count fields."""
    payload = svc.serialize()
    assert payload["node_count"] == len(payload["nodes"])
    assert payload["edge_count"] == len(payload["edges"])


def test_serialize_no_layout_for_small(svc: GraphService) -> None:
    """Small graph serialization has no layout key."""
    payload = svc.serialize(include_layout=True)
    # Small graph → compute_layout returns {} → no layout key added
    assert "layout" not in payload


# ---------------------------------------------------------------------------
# GraphNode / GraphEdge serialization
# ---------------------------------------------------------------------------


def test_graph_node_to_dict() -> None:
    """GraphNode.to_dict produces expected keys."""
    node = GraphNode(id="a:b", label="B", entity_type="a", case_count=3, risk_score=0.5)
    d = node.to_dict()
    assert d == {
        "id": "a:b",
        "label": "B",
        "entity_type": "a",
        "case_count": 3,
        "risk_score": 0.5,
        "data": {},
    }


def test_graph_edge_to_dict() -> None:
    """GraphEdge.to_dict produces expected keys."""
    edge = GraphEdge(source="a", target="b", weight=5, edge_type="shared-case")
    d = edge.to_dict()
    assert d == {"source": "a", "target": "b", "weight": 5, "edge_type": "shared-case"}


# ---------------------------------------------------------------------------
# Empty / None graph guard
# ---------------------------------------------------------------------------


def test_empty_adjacency() -> None:
    """Empty adjacency produces an empty graph."""
    svc = GraphService({})
    payload = svc.serialize()
    assert payload["node_count"] == 0
    assert payload["edges"] == []
    assert svc.get_neighbors("x") == {"seed": "x", "nodes": [], "edges": []}
    assert svc.detect_clusters() == []
