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
