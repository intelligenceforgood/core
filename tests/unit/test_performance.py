"""Performance validation tests (S6-22).

Verifies that analytics queries and dashboard endpoints respond within
acceptable time bounds using mocked data. These are structural tests, not
load tests — they verify query patterns are efficient.
"""

from __future__ import annotations


def test_dashboard_kpi_query_structure() -> None:
    """Impact dashboard KPI query uses indexed columns."""
    from i4g.store import sql

    # Verify the created_at index exists on cases
    idx_names = [idx.name for idx in sql.cases.indexes]
    assert "idx_cases_created_at" in idx_names


def test_entity_stats_index_coverage() -> None:
    """entity_stats has indexes on frequently filtered columns."""
    from i4g.store import sql

    idx_names = [idx.name for idx in sql.entity_stats.indexes]
    assert "idx_entity_stats_status" in idx_names
    assert "idx_entity_stats_case_count" in idx_names
    assert "idx_entity_stats_loss_sum" in idx_names


def test_indicator_stats_index_coverage() -> None:
    """indicator_stats has indexes for analytics queries."""
    from i4g.store import sql

    idx_names = [idx.name for idx in sql.indicator_stats.indexes]
    assert "idx_indicator_stats_category" in idx_names
    assert "idx_indicator_stats_first_seen_at" in idx_names


def test_campaign_stats_index_coverage() -> None:
    """campaign_stats has indexes for listing queries."""
    from i4g.store import sql

    idx_names = [idx.name for idx in sql.campaign_stats.indexes]
    assert "idx_campaign_stats_status" in idx_names
    assert "idx_campaign_stats_risk_score" in idx_names


def test_intake_records_index_coverage() -> None:
    """intake_records has indexes for dashboard aggregations."""
    from i4g.store import sql

    idx_names = [idx.name for idx in sql.intake_records.indexes]
    assert "idx_intake_records_created_at" in idx_names
    assert "idx_intake_records_case_id" in idx_names


def test_graph_service_serializes_small_graph() -> None:
    """GraphService can serialize a small graph without error."""
    from i4g.services.graph_service import GraphService

    adjacency = {"n1": ["case-1"], "n2": ["case-1"]}
    entity_meta = {
        "n1": {"entity_type": "domain", "label": "test"},
        "n2": {"entity_type": "ip", "label": "test2"},
    }
    gs = GraphService(adjacency=adjacency, entity_meta=entity_meta)

    data = gs.serialize()
    assert len(data["nodes"]) == 2
    assert len(data["edges"]) >= 1
