"""Unit tests for the analytics aggregation job.

Tests cover risk score computation, lifecycle transitions,
and the aggregation refresh against a temporary SQLite database.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from i4g.store.sql import (
    METADATA,
    campaign_stats,
    cases,
    entities,
    entity_stats,
    indicator_stats,
    indicators,
    intake_records,
    platform_kpis,
    threat_campaign_cases,
    threat_campaigns,
)
from i4g.worker.jobs.analytics_aggregation import (
    _anonymize_purged_entities,
    _next_lifecycle_state,
    _refresh_campaign_stats,
    _refresh_entity_stats,
    _refresh_indicator_stats,
    _refresh_platform_kpis,
    compute_campaign_risk_score,
)


def _make_session(db_path: Path) -> sessionmaker:
    """Create a sessionmaker with all TIFAP tables."""
    engine = sa.create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    METADATA.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


# ---------------------------------------------------------------------------
# Risk score computation
# ---------------------------------------------------------------------------


def test_risk_score_empty_campaign() -> None:
    """Zero values produce a zero score."""
    score = compute_campaign_risk_score(
        case_count=0,
        loss_sum=0.0,
        avg_risk=0.0,
        last_case_at=None,
        distinct_entity_types=0,
    )
    assert score == 0.0


def test_risk_score_maxed_out() -> None:
    """Maxed inputs should approach 100."""
    recent = datetime.now(tz=UTC) - timedelta(days=1)
    score = compute_campaign_risk_score(
        case_count=100,
        loss_sum=2_000_000,
        avg_risk=100.0,
        last_case_at=recent,
        distinct_entity_types=10,
    )
    assert score == 100.0


def test_risk_score_partial() -> None:
    """Intermediate values produce a mid-range score."""
    recent = datetime.now(tz=UTC) - timedelta(days=20)
    score = compute_campaign_risk_score(
        case_count=10,
        loss_sum=200_000,
        avg_risk=50.0,
        last_case_at=recent,
        distinct_entity_types=3,
    )
    assert 0.0 < score < 100.0


def test_risk_score_custom_weights() -> None:
    """Custom weights override defaults."""
    recent = datetime.now(tz=UTC) - timedelta(days=1)
    # Weights heavily favoring loss_sum
    weights = {
        "case_count": 0.0,
        "loss_sum": 1.0,
        "avg_risk": 0.0,
        "recency": 0.0,
        "indicator_diversity": 0.0,
    }
    score = compute_campaign_risk_score(
        case_count=50,
        loss_sum=500_000,
        avg_risk=50.0,
        last_case_at=recent,
        distinct_entity_types=4,
        weights=weights,
    )
    assert score == 50.0  # 500k / 1M = 0.5 * 1.0 * 100


# ---------------------------------------------------------------------------
# Lifecycle transitions
# ---------------------------------------------------------------------------


def test_lifecycle_closed_is_terminal() -> None:
    """Closed campaigns never auto-transition."""
    assert _next_lifecycle_state("closed", datetime.now(tz=UTC), None) is None


def test_lifecycle_emerging_to_active() -> None:
    """A recent case moves emerging → active."""
    recent = datetime.now(tz=UTC) - timedelta(days=3)
    assert _next_lifecycle_state("emerging", recent, None) == "active"


def test_lifecycle_to_declining() -> None:
    """No cases in 14+ days moves to declining."""
    old = datetime.now(tz=UTC) - timedelta(days=16)
    assert _next_lifecycle_state("active", old, None) == "declining"


def test_lifecycle_to_dormant() -> None:
    """No cases in 30+ days moves to dormant."""
    very_old = datetime.now(tz=UTC) - timedelta(days=35)
    assert _next_lifecycle_state("active", very_old, None) == "dormant"


def test_lifecycle_no_transition_needed() -> None:
    """Returns None when already in the correct state."""
    very_old = datetime.now(tz=UTC) - timedelta(days=35)
    assert _next_lifecycle_state("dormant", very_old, None) is None


# ---------------------------------------------------------------------------
# Aggregation refresh (integration-level)
# ---------------------------------------------------------------------------


def _seed_data(sf: sessionmaker) -> None:
    """Insert minimal test data for aggregation."""
    now = datetime.now(tz=UTC)
    with sf() as session:
        # Cases
        session.execute(
            cases.insert().values(
                case_id="c1",
                dataset="test",
                source_type="proactive",
                raw_text_sha256="hash1",
                status="open",
                risk_score=70.0,
                classification="phishing",
                classification_result=json.dumps({"label": "phishing"}),
                created_at=now,
                updated_at=now,
            )
        )
        session.execute(
            cases.insert().values(
                case_id="c2",
                dataset="test",
                source_type="reactive",
                raw_text_sha256="hash2",
                status="open",
                risk_score=50.0,
                classification="scam",
                created_at=now,
                updated_at=now,
            )
        )

        # Entities
        session.execute(
            entities.insert().values(
                entity_id="e1",
                case_id="c1",
                entity_type="wallet",
                canonical_value="0xABC",
                confidence=0.9,
                first_seen_at=now,
                last_seen_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        session.execute(
            entities.insert().values(
                entity_id="e2",
                case_id="c2",
                entity_type="wallet",
                canonical_value="0xABC",
                confidence=0.85,
                first_seen_at=now,
                last_seen_at=now,
                created_at=now,
                updated_at=now,
            )
        )

        # Indicators
        session.execute(
            indicators.insert().values(
                indicator_id="i1",
                case_id="c1",
                category="crypto",
                type="bitcoin",
                number="1BTC123",
                status="active",
                confidence=0.95,
                dataset="test",
                first_seen_at=now,
                last_seen_at=now,
                created_at=now,
                updated_at=now,
            )
        )

        # Intake records
        session.execute(
            intake_records.insert().values(
                intake_id="ir1",
                case_id="c1",
                loss_amount=5000.0,
                summary="Victim lost funds",
                created_at=now,
                updated_at=now,
            )
        )

        # Threat campaign and links
        session.execute(
            threat_campaigns.insert().values(
                campaign_id="tc1",
                name="Test Campaign",
                origin="manual",
                status="emerging",
                created_by="system",
                created_at=now,
                updated_at=now,
            )
        )
        session.execute(
            threat_campaign_cases.insert().values(
                campaign_id="tc1",
                case_id="c1",
                linked_by="system",
            )
        )
        session.execute(
            threat_campaign_cases.insert().values(
                campaign_id="tc1",
                case_id="c2",
                linked_by="system",
            )
        )

        session.commit()


def test_refresh_entity_stats(tmp_path: Path) -> None:
    """Entity stats are computed from entities + cases."""
    sf = _make_session(tmp_path / "agg.db")
    _seed_data(sf)

    with sf() as session:
        count = _refresh_entity_stats(session)
        session.commit()

    assert count >= 1

    with sf() as session:
        rows = session.execute(sa.select(entity_stats)).fetchall()
        assert len(rows) >= 1
        wallet_row = [r for r in rows if r.entity_type == "wallet"][0]
        assert wallet_row.case_count == 2
        assert wallet_row.canonical_value == "0xABC"


def test_refresh_indicator_stats(tmp_path: Path) -> None:
    """Indicator stats are computed from indicators."""
    sf = _make_session(tmp_path / "agg.db")
    _seed_data(sf)

    with sf() as session:
        count = _refresh_indicator_stats(session)
        session.commit()

    assert count >= 1

    with sf() as session:
        rows = session.execute(sa.select(indicator_stats)).fetchall()
        assert len(rows) >= 1


def test_refresh_campaign_stats(tmp_path: Path) -> None:
    """Campaign stats are computed for each threat campaign."""
    sf = _make_session(tmp_path / "agg.db")
    _seed_data(sf)

    with sf() as session:
        count = _refresh_campaign_stats(session)
        session.commit()

    assert count == 1

    with sf() as session:
        rows = session.execute(sa.select(campaign_stats)).fetchall()
        assert len(rows) == 1
        assert rows[0].case_count == 2
        assert rows[0].risk_score > 0


def test_refresh_platform_kpis(tmp_path: Path) -> None:
    """Platform KPIs are computed for daily and weekly periods."""
    sf = _make_session(tmp_path / "agg.db")
    _seed_data(sf)

    with sf() as session:
        count = _refresh_platform_kpis(session)
        session.commit()

    assert count == 2  # daily + weekly

    with sf() as session:
        rows = session.execute(sa.select(platform_kpis)).fetchall()
        assert len(rows) == 2


def test_anonymize_purged_entities(tmp_path: Path) -> None:
    """Entity stats for fully purged cases are anonymized."""
    sf = _make_session(tmp_path / "agg.db")
    now = datetime.now(tz=UTC)

    # Seed a purged case with an entity and entity_stats
    with sf() as session:
        session.execute(
            cases.insert().values(
                case_id="purged1",
                dataset="test",
                source_type="reactive",
                raw_text_sha256="purge_hash",
                status="open",
                risk_score=40.0,
                purged_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        session.execute(
            entities.insert().values(
                entity_id="ep1",
                case_id="purged1",
                entity_type="phone",
                canonical_value="+15551234567",
                confidence=0.9,
                created_at=now,
                updated_at=now,
            )
        )
        session.execute(
            entity_stats.insert().values(
                entity_type="phone",
                canonical_value="+15551234567",
                case_count=1,
                victim_count=1,
                loss_sum=1000.0,
                max_risk_score=40.0,
                avg_risk_score=40.0,
                status="active",
                updated_at=now,
            )
        )
        session.commit()

    with sf() as session:
        anonymized = _anonymize_purged_entities(session)
        session.commit()

    assert anonymized == 1

    with sf() as session:
        row = session.execute(sa.select(entity_stats).where(entity_stats.c.entity_type == "phone")).fetchone()
        assert row is not None
        assert row.purge_status == "anonymized"
        # Canonical value should now be a SHA-256 hash
        assert row.canonical_value != "+15551234567"
        assert len(row.canonical_value) == 64  # SHA-256 hex digest
