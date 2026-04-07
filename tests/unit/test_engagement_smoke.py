"""Integration smoke test for engagement scoping end-to-end.

Verifies the engagement lifecycle: create → activate → create case with scope →
list cases scoped → assign additional cases → summary.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa

from i4g.store import sql as sql_schema
from i4g.store.engagement_store import EngagementStore
from i4g.store.review_store import ReviewStore


@pytest.fixture()
def db_session_factory(tmp_path):
    """Create a fresh SQLite database with all tables."""
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    engine = sa.create_engine(db_url)
    sql_schema.METADATA.create_all(engine)

    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=engine)
    return factory


@pytest.fixture()
def engagement_store(db_session_factory):
    return EngagementStore(session_factory=db_session_factory)


@pytest.fixture()
def review_store(db_session_factory):
    return ReviewStore(session_factory=db_session_factory)


def _insert_case(session_factory, case_id: str, engagement_id: str | None = None):
    """Insert a minimal case row and enqueue for review."""
    now = datetime.now(UTC)
    review_id = str(uuid.uuid4())
    with session_factory() as session:
        session.execute(
            sa.insert(sql_schema.cases).values(
                case_id=case_id,
                dataset="test",
                source_type="manual",
                classification="fraud",
                classification_status="classified",
                confidence=0.9,
                raw_text_sha256=f"hash-{case_id}",
                status="open",
                description="Test case",
                engagement_id=engagement_id,
                created_at=now,
                updated_at=now,
            )
        )
        session.execute(
            sa.insert(sql_schema.review_queue).values(
                review_id=review_id,
                case_id=case_id,
                status="new",
                priority="medium",
                queued_at=now,
                last_updated=now,
            )
        )
        session.commit()


class TestEngagementLifecycle:
    """End-to-end engagement scoping smoke test."""

    def test_create_activate_scope(self, engagement_store, review_store, db_session_factory):
        """Full lifecycle: create engagement, activate, assign cases, verify scoping."""
        # 1. Create engagement
        eng = engagement_store.create(
            name="Q1 2026 Investigation",
            description="Quarterly engagement",
            created_by="admin@test.io",
        )
        eng_id = eng["engagement_id"]
        assert eng["status"] == "draft"

        # 2. Activate
        updated = engagement_store.update(eng_id, status="active")
        assert updated["status"] == "active"

        # 3. Create cases — some scoped, some not
        scoped_ids = [f"case-scoped-{i}" for i in range(3)]
        unscoped_ids = [f"case-unscoped-{i}" for i in range(2)]

        for cid in scoped_ids:
            _insert_case(db_session_factory, cid, engagement_id=eng_id)
        for cid in unscoped_ids:
            _insert_case(db_session_factory, cid, engagement_id=None)

        # 4. Verify scoped dashboard summary
        scoped = review_store.get_dashboard_summary(engagement_id=eng_id)
        assert scoped["summary"]["active"] == 3

        unscoped = review_store.get_dashboard_summary()
        assert unscoped["summary"]["active"] == 5

        # 5. Assign unscoped cases via store
        engagement_store.assign_cases(eng_id, unscoped_ids)
        all_scoped = review_store.get_dashboard_summary(engagement_id=eng_id)
        assert all_scoped["summary"]["active"] == 5

        # 6. Summary
        summary = engagement_store.get_summary(eng_id)
        assert summary["case_count"] == 5
        assert summary["status"] == "active"

    def test_remove_case_from_engagement(self, engagement_store, review_store, db_session_factory):
        """Removing a case from an engagement makes it globally visible only."""
        eng = engagement_store.create(name="Temp", created_by="admin@test.io")
        eng_id = eng["engagement_id"]
        engagement_store.update(eng_id, status="active")

        _insert_case(db_session_factory, "case-rm-1", engagement_id=eng_id)
        assert review_store.get_dashboard_summary(engagement_id=eng_id)["summary"]["active"] == 1

        engagement_store.remove_cases(eng_id, ["case-rm-1"])
        assert review_store.get_dashboard_summary(engagement_id=eng_id)["summary"]["active"] == 0
        assert review_store.get_dashboard_summary()["summary"]["active"] == 1

    def test_engagement_id_on_cases_column(self, db_session_factory):
        """Verify the engagement_id FK column exists and works."""
        eng_id = str(uuid.uuid4())
        # Create engagement first (FK constraint)
        now = datetime.now(UTC)
        with db_session_factory() as session:
            session.execute(
                sa.insert(sql_schema.engagements).values(
                    engagement_id=eng_id,
                    name="FK test",
                    status="active",
                    created_by="test",
                    created_at=now,
                    updated_at=now,
                )
            )
            session.commit()

        _insert_case(db_session_factory, "case-fk-1", engagement_id=eng_id)

        with db_session_factory() as session:
            row = session.execute(
                sa.select(sql_schema.cases.c.engagement_id).where(sql_schema.cases.c.case_id == "case-fk-1")
            ).scalar()
            assert row == eng_id
