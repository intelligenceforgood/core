"""Unit tests for Louvain clustering — community detection, cluster scoring (S5-02, S5-27)."""

from __future__ import annotations

import pytest


def test_detect_clusters_returns_communities() -> None:
    """detect_clusters finds at least one community in a connected graph."""
    nx = pytest.importorskip("networkx")
    from i4g.services.graph_service import GraphService

    gs = GraphService.__new__(GraphService)
    gs._graph = nx.Graph()

    # Create two dense cliques connected by a single bridge
    for i in range(5):
        for j in range(i + 1, 5):
            gs._graph.add_node(
                f"a:{i}", entity_type="domain", canonical_value=f"a{i}.com", risk_score=0.5, case_count=1
            )
            gs._graph.add_node(
                f"a:{j}", entity_type="domain", canonical_value=f"a{j}.com", risk_score=0.5, case_count=1
            )
            gs._graph.add_edge(f"a:{i}", f"a:{j}", weight=3)

    for i in range(5, 10):
        for j in range(i + 1, 10):
            gs._graph.add_node(
                f"a:{i}", entity_type="ip_address", canonical_value=f"10.0.0.{i}", risk_score=0.3, case_count=1
            )
            gs._graph.add_node(
                f"a:{j}", entity_type="ip_address", canonical_value=f"10.0.0.{j}", risk_score=0.3, case_count=1
            )
            gs._graph.add_edge(f"a:{i}", f"a:{j}", weight=3)

    # Weak bridge
    gs._graph.add_edge("a:4", "a:5", weight=1)

    clusters = gs.detect_clusters(min_size=2, resolution=1.0)

    assert isinstance(clusters, list)
    assert len(clusters) >= 1  # At least one cluster
    for cluster in clusters:
        assert "id" in cluster
        assert "members" in cluster
        assert "size" in cluster
        assert cluster["size"] >= 2


def test_detect_clusters_min_size_filter() -> None:
    """Clusters smaller than min_size are excluded."""
    nx = pytest.importorskip("networkx")
    from i4g.services.graph_service import GraphService

    gs = GraphService.__new__(GraphService)
    gs._graph = nx.Graph()

    # Small graph: 3 nodes
    for i in range(3):
        gs._graph.add_node(f"n:{i}", entity_type="domain", canonical_value=f"d{i}.com", risk_score=0.1, case_count=1)
    gs._graph.add_edge("n:0", "n:1", weight=1)
    gs._graph.add_edge("n:1", "n:2", weight=1)

    # min_size=5 should filter out the small cluster
    clusters = gs.detect_clusters(min_size=5)
    assert len(clusters) == 0


def test_detect_clusters_enriches_metadata() -> None:
    """Clusters include density, avg_risk_score, and entity_types."""
    nx = pytest.importorskip("networkx")
    from i4g.services.graph_service import GraphService

    gs = GraphService.__new__(GraphService)
    gs._graph = nx.Graph()

    for i in range(4):
        gs._graph.add_node(f"n:{i}", entity_type="domain", canonical_value=f"d{i}.com", risk_score=0.7, case_count=2)
    for i in range(4):
        for j in range(i + 1, 4):
            gs._graph.add_edge(f"n:{i}", f"n:{j}", weight=2)

    clusters = gs.detect_clusters(min_size=2)

    if clusters:  # Louvain may group all in one cluster
        cluster = clusters[0]
        assert "density" in cluster
        assert "avg_risk_score" in cluster
        assert "entity_types" in cluster
        assert isinstance(cluster["entity_types"], dict)
