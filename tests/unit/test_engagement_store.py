"""Unit tests for EngagementStore."""

from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from i4g.store.engagement_store import EngagementStore
from i4g.store.sql import METADATA


def _make_store(db_path: Path) -> tuple[EngagementStore, sessionmaker]:
    """Build an EngagementStore backed by a temporary SQLite file."""
    engine = sa.create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    METADATA.create_all(engine)
    sf = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return EngagementStore(session_factory=sf), sf


def _insert_case(sf: sessionmaker, case_id: str, engagement_id: str | None = None) -> None:
    """Insert a minimal case row for testing."""
    from i4g.store import sql as sql_schema

    with sf() as session:
        session.execute(
            sa.insert(sql_schema.cases).values(
                case_id=case_id,
                dataset="test",
                source_type="test",
                raw_text_sha256=case_id,
                engagement_id=engagement_id,
            )
        )
        session.commit()


class TestEngagementCRUD:
    def test_create_and_get(self, tmp_path):
        store, _ = _make_store(tmp_path / "test.db")
        eng = store.create(name="Spring 2026", description="UAB competition")
        assert eng["name"] == "Spring 2026"
        assert eng["status"] == "draft"
        assert eng["engagement_id"]

        fetched = store.get(eng["engagement_id"])
        assert fetched is not None
        assert fetched["name"] == "Spring 2026"

    def test_get_nonexistent_returns_none(self, tmp_path):
        store, _ = _make_store(tmp_path / "test.db")
        assert store.get("nonexistent-id") is None

    def test_list_all(self, tmp_path):
        store, _ = _make_store(tmp_path / "test.db")
        store.create(name="Eng 1")
        store.create(name="Eng 2")
        result = store.list()
        assert len(result) == 2

    def test_list_by_status(self, tmp_path):
        store, _ = _make_store(tmp_path / "test.db")
        store.create(name="Draft", status="draft")
        eng2 = store.create(name="Active", status="active")
        result = store.list(status="active")
        assert len(result) == 1
        assert result[0]["engagement_id"] == eng2["engagement_id"]

    def test_update_name(self, tmp_path):
        store, _ = _make_store(tmp_path / "test.db")
        eng = store.create(name="Old Name")
        updated = store.update(eng["engagement_id"], name="New Name")
        assert updated is not None
        assert updated["name"] == "New Name"

    def test_update_nonexistent_returns_none(self, tmp_path):
        store, _ = _make_store(tmp_path / "test.db")
        assert store.update("no-such-id", name="x") is None

    def test_create_invalid_status_raises(self, tmp_path):
        store, _ = _make_store(tmp_path / "test.db")
        with pytest.raises(ValueError, match="Invalid status"):
            store.create(name="Bad", status="invalid")

    def test_archive(self, tmp_path):
        store, _ = _make_store(tmp_path / "test.db")
        eng = store.create(name="To Archive", status="active")
        store.update(eng["engagement_id"], status="completed")
        archived = store.archive(eng["engagement_id"])
        assert archived is not None
        assert archived["status"] == "archived"


class TestLifecycleTransitions:
    def test_draft_to_active(self, tmp_path):
        store, _ = _make_store(tmp_path / "test.db")
        eng = store.create(name="Test")
        updated = store.update(eng["engagement_id"], status="active")
        assert updated["status"] == "active"

    def test_active_to_completed(self, tmp_path):
        store, _ = _make_store(tmp_path / "test.db")
        eng = store.create(name="Test", status="active")
        updated = store.update(eng["engagement_id"], status="completed")
        assert updated["status"] == "completed"

    def test_invalid_transition_raises(self, tmp_path):
        store, _ = _make_store(tmp_path / "test.db")
        eng = store.create(name="Test")  # draft
        with pytest.raises(ValueError, match="Invalid transition"):
            store.update(eng["engagement_id"], status="archived")

    def test_admin_revert_to_draft(self, tmp_path):
        store, _ = _make_store(tmp_path / "test.db")
        eng = store.create(name="Test", status="active")
        updated = store.update(eng["engagement_id"], status="draft")
        assert updated["status"] == "draft"


class TestCaseAssignment:
    def test_assign_cases(self, tmp_path):
        store, sf = _make_store(tmp_path / "test.db")
        eng = store.create(name="Test Engagement")
        _insert_case(sf, "case-1")
        _insert_case(sf, "case-2")
        count = store.assign_cases(eng["engagement_id"], ["case-1", "case-2"])
        assert count == 2

    def test_remove_cases(self, tmp_path):
        store, sf = _make_store(tmp_path / "test.db")
        eng = store.create(name="Test")
        _insert_case(sf, "case-1", engagement_id=eng["engagement_id"])
        count = store.remove_cases(eng["engagement_id"], ["case-1"])
        assert count == 1

    def test_remove_only_from_own_engagement(self, tmp_path):
        store, sf = _make_store(tmp_path / "test.db")
        eng1 = store.create(name="Eng 1")
        eng2 = store.create(name="Eng 2")
        _insert_case(sf, "case-1", engagement_id=eng1["engagement_id"])
        # Trying to remove case-1 from eng2 should affect 0 rows
        count = store.remove_cases(eng2["engagement_id"], ["case-1"])
        assert count == 0

    def test_assign_empty_list(self, tmp_path):
        store, _ = _make_store(tmp_path / "test.db")
        eng = store.create(name="Test")
        count = store.assign_cases(eng["engagement_id"], [])
        assert count == 0


class TestSummary:
    def test_summary_with_no_cases(self, tmp_path):
        store, _ = _make_store(tmp_path / "test.db")
        eng = store.create(name="Empty")
        summary = store.get_summary(eng["engagement_id"])
        assert summary is not None
        assert summary["case_count"] == 0
        assert summary["cases_reviewed"] == 0
        assert summary["review_completion_pct"] == 0.0

    def test_summary_with_cases(self, tmp_path):
        store, sf = _make_store(tmp_path / "test.db")
        eng = store.create(name="Test")
        eid = eng["engagement_id"]
        _insert_case(sf, "case-1", engagement_id=eid)
        _insert_case(sf, "case-2", engagement_id=eid)
        _insert_case(sf, "case-3", engagement_id=eid)

        summary = store.get_summary(eid)
        assert summary["case_count"] == 3
        assert summary["cases_reviewed"] == 0
        assert summary["cases_remaining"] == 3

    def test_summary_nonexistent_returns_none(self, tmp_path):
        store, _ = _make_store(tmp_path / "test.db")
        assert store.get_summary("no-such-id") is None


# ---------------------------------------------------------------------------
# Phase 3 — Extended analytics & Leaderboard
# ---------------------------------------------------------------------------


def _seed_review_data(
    sf: sessionmaker,
    engagement_id: str,
    analysts: list[str],
) -> None:
    """Insert review_queue + review_actions rows for engagement cases."""
    from datetime import UTC, datetime

    from i4g.store import sql as sql_schema

    now = datetime.now(UTC)
    with sf() as session:
        cases = session.execute(
            sa.select(sql_schema.cases.c.case_id).where(sql_schema.cases.c.engagement_id == engagement_id)
        ).fetchall()
        for idx, (case_id,) in enumerate(cases):
            review_id = f"rev-{case_id}"
            analyst = analysts[idx % len(analysts)]
            session.execute(
                sa.insert(sql_schema.review_queue).values(
                    review_id=review_id,
                    case_id=case_id,
                    queued_at=now,
                    priority="medium",
                    status="accepted",
                    assigned_to=analyst,
                )
            )
            session.execute(
                sa.insert(sql_schema.review_actions).values(
                    action_id=f"act-{case_id}",
                    review_id=review_id,
                    actor=analyst,
                    action="classify",
                    created_at=now,
                )
            )
        session.commit()


def _seed_analyst_stats(
    sf: sessionmaker,
    engagement_id: str,
    stats: list[dict],
) -> None:
    """Insert rows into engagement_analyst_stats directly."""
    from datetime import UTC, datetime

    from i4g.store import sql as sql_schema

    now = datetime.now(UTC)
    with sf() as session:
        for s in stats:
            session.execute(
                sa.insert(sql_schema.engagement_analyst_stats).values(
                    engagement_id=engagement_id,
                    analyst_email=s["analyst_email"],
                    cases_reviewed=s.get("cases_reviewed", 0),
                    avg_review_time_seconds=s.get("avg_review_time_seconds"),
                    classification_accuracy=s.get("classification_accuracy"),
                    risk_score_mae=s.get("risk_score_mae"),
                    actions_logged=s.get("actions_logged", 0),
                    last_activity_at=s.get("last_activity_at"),
                    computed_at=now,
                )
            )
        session.commit()


class TestExtendedSummary:
    def test_extended_summary_basic(self, tmp_path):
        store, sf = _make_store(tmp_path / "test.db")
        eng = store.create(name="Test Ext Summary", status="active")
        eid = eng["engagement_id"]
        _insert_case(sf, "case-1", engagement_id=eid)
        _insert_case(sf, "case-2", engagement_id=eid)

        summary = store.get_extended_summary(eid)
        assert summary is not None
        assert summary["case_count"] == 2
        assert "classification_distribution" in summary
        assert "top_classifications" in summary
        assert "analyst_count" in summary
        assert summary["analyst_count"] == 0  # no reviews yet

    def test_extended_summary_with_analysts(self, tmp_path):
        store, sf = _make_store(tmp_path / "test.db")
        eng = store.create(name="With Analysts", status="active")
        eid = eng["engagement_id"]
        _insert_case(sf, "case-1", engagement_id=eid)
        _insert_case(sf, "case-2", engagement_id=eid)
        _seed_review_data(sf, eid, ["alice@test.io", "bob@test.io"])

        summary = store.get_extended_summary(eid)
        assert summary["analyst_count"] == 2

    def test_extended_summary_days_elapsed(self, tmp_path):
        from datetime import UTC, datetime, timedelta

        store, sf = _make_store(tmp_path / "test.db")
        eng = store.create(
            name="With Dates",
            status="active",
            starts_at=datetime.now(UTC) - timedelta(days=5),
            ends_at=datetime.now(UTC) + timedelta(days=10),
        )
        summary = store.get_extended_summary(eng["engagement_id"])
        assert summary["days_elapsed"] == 5
        assert summary["days_remaining"] is not None
        assert summary["days_remaining"] >= 9

    def test_extended_summary_avg_review_time(self, tmp_path):
        store, sf = _make_store(tmp_path / "test.db")
        eng = store.create(name="With Stats", status="active")
        eid = eng["engagement_id"]
        _insert_case(sf, "case-1", engagement_id=eid)
        _seed_analyst_stats(
            sf,
            eid,
            [
                {"analyst_email": "alice@test.io", "cases_reviewed": 5, "avg_review_time_seconds": 360},
                {"analyst_email": "bob@test.io", "cases_reviewed": 3, "avg_review_time_seconds": 720},
            ],
        )

        summary = store.get_extended_summary(eid)
        # Average of 360 and 720 = 540 seconds / 3600 = 0.15 → rounded to 0.1
        assert summary["avg_review_time_hours"] == 0.1

    def test_extended_summary_nonexistent_returns_none(self, tmp_path):
        store, _ = _make_store(tmp_path / "test.db")
        assert store.get_extended_summary("no-such-id") is None


class TestLeaderboard:
    def test_leaderboard_empty(self, tmp_path):
        store, _ = _make_store(tmp_path / "test.db")
        eng = store.create(name="Empty Eng", status="active")
        entries = store.get_leaderboard(eng["engagement_id"])
        assert entries == []

    def test_leaderboard_nonexistent_returns_none(self, tmp_path):
        store, _ = _make_store(tmp_path / "test.db")
        assert store.get_leaderboard("no-such-id") is None

    def test_leaderboard_ranking(self, tmp_path):
        store, sf = _make_store(tmp_path / "test.db")
        eng = store.create(name="Ranked Eng", status="active")
        eid = eng["engagement_id"]
        _seed_analyst_stats(
            sf,
            eid,
            [
                {
                    "analyst_email": "alice@test.io",
                    "cases_reviewed": 10,
                    "classification_accuracy": 0.9,
                    "risk_score_mae": 5.0,
                    "actions_logged": 20,
                },
                {
                    "analyst_email": "bob@test.io",
                    "cases_reviewed": 5,
                    "classification_accuracy": 0.7,
                    "risk_score_mae": 10.0,
                    "actions_logged": 10,
                },
            ],
        )

        entries = store.get_leaderboard(eid)
        assert len(entries) == 2
        assert entries[0]["rank"] == 1
        assert entries[1]["rank"] == 2
        # Alice should rank higher due to more reviews and higher accuracy
        assert entries[0]["analyst_email"] == "alice@test.io"
        assert entries[0]["composite_score"] > entries[1]["composite_score"]

    def test_leaderboard_with_custom_weights(self, tmp_path):
        store, sf = _make_store(tmp_path / "test.db")
        eng = store.create(name="Custom Weights", status="active")
        eid = eng["engagement_id"]
        _seed_analyst_stats(
            sf,
            eid,
            [
                {
                    "analyst_email": "alice@test.io",
                    "cases_reviewed": 10,
                    "classification_accuracy": 0.5,
                    "actions_logged": 20,
                },
                {
                    "analyst_email": "bob@test.io",
                    "cases_reviewed": 3,
                    "classification_accuracy": 0.99,
                    "actions_logged": 5,
                },
            ],
        )

        # Heavily weight accuracy only
        entries = store.get_leaderboard(eid, weights={"accuracy": 1.0, "throughput": 0.0, "quality": 0.0})
        assert entries[0]["analyst_email"] == "bob@test.io"

    def test_leaderboard_entries_have_required_fields(self, tmp_path):
        store, sf = _make_store(tmp_path / "test.db")
        eng = store.create(name="Fields Check", status="active")
        eid = eng["engagement_id"]
        _seed_analyst_stats(
            sf,
            eid,
            [
                {
                    "analyst_email": "alice@test.io",
                    "cases_reviewed": 5,
                    "classification_accuracy": 0.8,
                    "actions_logged": 10,
                },
            ],
        )

        entries = store.get_leaderboard(eid)
        entry = entries[0]
        assert "rank" in entry
        assert "analyst_email" in entry
        assert "cases_reviewed" in entry
        assert "composite_score" in entry
        assert "classification_accuracy" in entry
        assert "actions_logged" in entry

    def test_leaderboard_limit(self, tmp_path):
        store, sf = _make_store(tmp_path / "test.db")
        eng = store.create(name="Limit Test", status="active")
        eid = eng["engagement_id"]
        _seed_analyst_stats(
            sf,
            eid,
            [{"analyst_email": f"analyst{i}@test.io", "cases_reviewed": i, "actions_logged": i} for i in range(1, 6)],
        )

        entries = store.get_leaderboard(eid, limit=3)
        assert len(entries) == 3
