"""Unit tests for temporal graph animation data generation (S5-01, S5-26)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from i4g.services.graph_service import GraphService


def test_temporal_snapshots_basic() -> None:
    """get_temporal_snapshots generates snapshots for each interval."""
    nx = pytest.importorskip("networkx")
    gs = GraphService.__new__(GraphService)
    gs._graph = nx.Graph()

    now = datetime.now(UTC)
    t1 = now - timedelta(days=30)
    t2 = now - timedelta(days=15)

    gs._graph.add_node(
        "wallet:abc123",
        entity_type="crypto_wallet",
        canonical_value="abc123",
        risk_score=0.8,
        case_count=3,
    )
    gs._graph.add_node(
        "wallet:def456",
        entity_type="crypto_wallet",
        canonical_value="def456",
        risk_score=0.5,
        case_count=1,
    )
    gs._graph.add_edge("wallet:abc123", "wallet:def456", weight=2)

    timestamps = {
        "wallet:abc123": t1.isoformat(),
        "wallet:def456": t2.isoformat(),
    }

    snapshots = gs.get_temporal_snapshots(timestamps)

    assert len(snapshots) >= 1
    # Last snapshot should have both nodes
    assert snapshots[-1]["node_count"] == 2


def test_temporal_snapshots_empty_graph() -> None:
    """Temporal snapshots with no timestamps returns empty."""
    nx = pytest.importorskip("networkx")
    gs = GraphService.__new__(GraphService)
    gs._graph = nx.Graph()

    # No nodes, so timestamps dict is empty → returns []
    snapshots = gs.get_temporal_snapshots(timestamps={})
    assert len(snapshots) == 0
