"""Unit tests for AnalyticsStore read-only queries."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from i4g.store.analytics_store import AnalyticsStore
from i4g.store.sql import METADATA, cases, entities, entity_stats, indicator_stats, platform_kpis


def _make_store(db_path: Path) -> tuple[AnalyticsStore, sessionmaker]:
    """Build an AnalyticsStore backed by a temporary SQLite file."""
    engine = sa.create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    METADATA.create_all(engine)
    sf = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return AnalyticsStore(session_factory=sf), sf


def _seed_entity_stats(sf: sessionmaker) -> None:
    """Insert sample entity_stats rows."""
    now = datetime.now(tz=UTC)
    with sf() as session:
        session.execute(
            entity_stats.insert().values(
                entity_type="wallet",
                canonical_value="0xABC123",
                case_count=5,
                victim_count=3,
                loss_sum=50000.00,
                max_risk_score=85.0,
                avg_risk_score=70.0,
                status="active",
                campaign_ids=json.dumps(["camp-1"]),
                top_classifications=json.dumps([{"label": "phishing", "count": 3}]),
                updated_at=now,
            )
        )
        session.execute(
            entity_stats.insert().values(
                entity_type="email",
                canonical_value="scam@example.com",
                case_count=2,
                victim_count=1,
                loss_sum=10000.00,
                max_risk_score=60.0,
                avg_risk_score=55.0,
                status="active",
                updated_at=now,
            )
        )
        session.commit()


def _seed_indicator_stats(sf: sessionmaker) -> None:
    """Insert sample indicator_stats rows."""
    now = datetime.now(tz=UTC)
    with sf() as session:
        session.execute(
            indicator_stats.insert().values(
                indicator_id="ind-001",
                category="cryptocurrency",
                type="bitcoin",
                number="1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
                case_count=3,
                loss_sum=25000.00,
                max_risk_score=90.0,
                updated_at=now,
            )
        )
        session.commit()


def test_list_entity_stats(tmp_path: Path) -> None:
    """Entity stats can be listed with default pagination."""
    store, sf = _make_store(tmp_path / "analytics.db")
    _seed_entity_stats(sf)

    results = store.list_entity_stats()
    assert len(results) == 2


def test_list_entity_stats_by_type(tmp_path: Path) -> None:
    """Entity stats can be filtered by entity_type."""
    store, sf = _make_store(tmp_path / "analytics.db")
    _seed_entity_stats(sf)

    results = store.list_entity_stats(entity_type="wallet")
    assert len(results) == 1
    assert results[0]["canonical_value"] == "0xABC123"


def test_get_entity_stat(tmp_path: Path) -> None:
    """A specific entity stat can be retrieved."""
    store, sf = _make_store(tmp_path / "analytics.db")
    _seed_entity_stats(sf)

    result = store.get_entity_stat("wallet", "0xABC123")
    assert result is not None
    assert result["case_count"] == 5
    assert result["loss_sum"] == 50000.00


def test_get_entity_stat_not_found(tmp_path: Path) -> None:
    """Returns None for non-existent entity stat."""
    store, sf = _make_store(tmp_path / "analytics.db")

    result = store.get_entity_stat("wallet", "nonexistent")
    assert result is None


def test_list_indicator_stats(tmp_path: Path) -> None:
    """Indicator stats can be listed."""
    store, sf = _make_store(tmp_path / "analytics.db")
    _seed_indicator_stats(sf)

    results = store.list_indicator_stats()
    assert len(results) == 1
    assert results[0]["indicator_id"] == "ind-001"


def test_get_indicator_stat(tmp_path: Path) -> None:
    """A specific indicator stat can be retrieved."""
    store, sf = _make_store(tmp_path / "analytics.db")
    _seed_indicator_stats(sf)

    result = store.get_indicator_stat("ind-001")
    assert result is not None
    assert result["case_count"] == 3


def test_list_platform_kpis(tmp_path: Path) -> None:
    """Platform KPIs can be listed."""
    store, sf = _make_store(tmp_path / "analytics.db")
    now = datetime.now(tz=UTC)

    with sf() as session:
        session.execute(
            platform_kpis.insert().values(
                period_type="daily",
                period_start=date(2025, 1, 15),
                engagement_id="__global__",
                total_cases=10,
                proactive_cases=3,
                reactive_cases=7,
                total_loss=100000.00,
                new_indicators=5,
                new_entities=8,
                updated_at=now,
            )
        )
        session.commit()

    results = store.list_platform_kpis(period_type="daily")
    assert len(results) == 1
    assert results[0]["total_cases"] == 10


# ---------------------------------------------------------------------------
# Entity status updates (Sprint 4 — S4-14/S4-44)
# ---------------------------------------------------------------------------


def test_update_entity_status(tmp_path: Path) -> None:
    """Entity status can be updated via update_entity_status."""
    store, sf = _make_store(tmp_path / "analytics.db")
    _seed_entity_stats(sf)

    success = store.update_entity_status(
        entity_type="wallet",
        canonical_value="0xABC123",
        status="flagged",
    )
    assert success is True

    entity = store.get_entity_stat("wallet", "0xABC123")
    assert entity["status"] == "flagged"


def test_update_entity_status_not_found(tmp_path: Path) -> None:
    """Updating status of a non-existent entity returns False."""
    store, sf = _make_store(tmp_path / "analytics.db")
    _seed_entity_stats(sf)

    success = store.update_entity_status(
        entity_type="wallet",
        canonical_value="nonexistent",
        status="dormant",
    )
    assert success is False


# ---------------------------------------------------------------------------
# get_entity_neighbors — dialect-aware string aggregation regression test
# ---------------------------------------------------------------------------


def _seed_entities_for_neighbors(sf: sessionmaker) -> None:
    """Insert cases + entities so two entities share a case."""
    import uuid

    now = datetime.now(tz=UTC)
    with sf() as session:
        # Two cases
        for cid in ("case-1", "case-2"):
            session.execute(
                cases.insert().values(
                    case_id=cid,
                    dataset="test",
                    source_type="reactive",
                    raw_text_sha256=f"sha-{cid}",
                    created_at=now,
                    updated_at=now,
                )
            )
        # Seed entity: wallet 0xSEED appears in case-1 and case-2
        for cid in ("case-1", "case-2"):
            session.execute(
                entities.insert().values(
                    entity_id=str(uuid.uuid4()),
                    case_id=cid,
                    entity_type="wallet",
                    canonical_value="0xSEED",
                    confidence=0.9,
                    created_at=now,
                    updated_at=now,
                )
            )
        # Neighbor entity: email bad@example.com shares case-1 with the seed
        session.execute(
            entities.insert().values(
                entity_id=str(uuid.uuid4()),
                case_id="case-1",
                entity_type="email",
                canonical_value="bad@example.com",
                confidence=0.8,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


def test_get_entity_neighbors(tmp_path: Path) -> None:
    """get_entity_neighbors returns neighbors with shared_case_ids as a list.

    Regression test: previously used SQLite-only ``group_concat`` which fails
    on PostgreSQL.  Now uses ``dialect_group_concat`` helper.
    """
    store, sf = _make_store(tmp_path / "analytics.db")
    _seed_entity_stats(sf)
    _seed_entities_for_neighbors(sf)

    neighbors = store.get_entity_neighbors("wallet", "0xSEED")
    assert len(neighbors) == 1
    assert neighbors[0]["entity_type"] == "email"
    assert neighbors[0]["canonical_value"] == "bad@example.com"
    assert neighbors[0]["shared_cases"] == 1
    assert "case-1" in neighbors[0]["shared_case_ids"]
