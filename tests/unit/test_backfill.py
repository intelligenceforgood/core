"""Unit tests for the backfill framework."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from i4g.backfill.lock import acquire_lock, refresh_lock, release_lock, task_lock
from i4g.backfill.registry import all_tasks
from i4g.store.sql import METADATA, backfill_locks


def _engine_and_session(tmp_path: object) -> tuple[sa.engine.Engine, sessionmaker[Session]]:
    """Create a file-based SQLite engine with relevant tables."""
    db_path = tmp_path / "test_backfill.db"  # type: ignore[operator]
    engine = sa.create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    METADATA.create_all(engine, checkfirst=True)
    sf = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return engine, sf


class TestAdvisoryLock:
    """Tests for the database-backed advisory lock."""

    def test_acquire_and_release(self, tmp_path):
        _, sf = _engine_and_session(tmp_path)
        with sf() as session:
            holder = acquire_lock("test-task", session, ttl_seconds=60)
            assert holder is not None

        # Lock should be visible
        with sf() as session:
            row = session.execute(sa.select(backfill_locks).where(backfill_locks.c.task_name == "test-task")).fetchone()
            assert row is not None
            assert row.holder_id == holder

        # Release
        with sf() as session:
            release_lock("test-task", holder, session)

        # Lock should be gone
        with sf() as session:
            row = session.execute(sa.select(backfill_locks).where(backfill_locks.c.task_name == "test-task")).fetchone()
            assert row is None

    def test_contention_blocks_second_acquire(self, tmp_path):
        _, sf = _engine_and_session(tmp_path)

        # First acquire succeeds
        with sf() as session:
            holder1 = acquire_lock("test-task", session, ttl_seconds=300)
            assert holder1 is not None

        # Second acquire fails
        with sf() as session:
            holder2 = acquire_lock("test-task", session, ttl_seconds=300)
            assert holder2 is None

        # Cleanup
        with sf() as session:
            release_lock("test-task", holder1, session)

    def test_expired_lock_is_reaped(self, tmp_path):
        _, sf = _engine_and_session(tmp_path)

        # Insert an already-expired lock
        with sf() as session:
            session.execute(
                sa.insert(backfill_locks).values(
                    task_name="test-task",
                    holder_id="old-holder",
                    acquired_at=datetime.now(UTC) - timedelta(hours=2),
                    expires_at=datetime.now(UTC) - timedelta(hours=1),
                )
            )
            session.commit()

        # New acquire should succeed (reaping the expired one)
        with sf() as session:
            holder = acquire_lock("test-task", session, ttl_seconds=60)
            assert holder is not None

        with sf() as session:
            release_lock("test-task", holder, session)

    def test_refresh_lock_extends_ttl(self, tmp_path):
        _, sf = _engine_and_session(tmp_path)

        with sf() as session:
            holder = acquire_lock("test-task", session, ttl_seconds=60)
            assert holder is not None

        with sf() as session:
            result = refresh_lock("test-task", holder, session, ttl_seconds=7200)
            assert result is True

        # Verify expiry was extended
        with sf() as session:
            row = session.execute(
                sa.select(backfill_locks.c.expires_at).where(backfill_locks.c.task_name == "test-task")
            ).fetchone()
            assert row is not None
            # Should expire well in the future (compare naive for SQLite compat)
            expires = row.expires_at.replace(tzinfo=None) if row.expires_at.tzinfo else row.expires_at
            assert expires > datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)

        with sf() as session:
            release_lock("test-task", holder, session)

    def test_refresh_returns_false_if_lock_lost(self, tmp_path):
        _, sf = _engine_and_session(tmp_path)

        with sf() as session:
            result = refresh_lock("nonexistent", "fake-holder", session, ttl_seconds=60)
            assert result is False

    def test_task_lock_context_manager(self, tmp_path):
        _, sf = _engine_and_session(tmp_path)

        with task_lock("test-task", sf, ttl_seconds=60) as holder:
            assert holder is not None
            # Lock should be held
            with sf() as session:
                row = session.execute(
                    sa.select(backfill_locks.c.holder_id).where(backfill_locks.c.task_name == "test-task")
                ).fetchone()
                assert row is not None

        # After exit, lock should be released
        with sf() as session:
            row = session.execute(sa.select(backfill_locks).where(backfill_locks.c.task_name == "test-task")).fetchone()
            assert row is None

    def test_task_lock_contention_yields_none(self, tmp_path):
        _, sf = _engine_and_session(tmp_path)

        # Pre-acquire
        with sf() as session:
            holder1 = acquire_lock("test-task", session, ttl_seconds=300)

        with task_lock("test-task", sf) as holder:
            assert holder is None

        # Cleanup
        with sf() as session:
            release_lock("test-task", holder1, session)


class TestRegistry:
    """Tests for the backfill task registry."""

    def test_all_tasks_are_registered(self):
        tasks = all_tasks()
        expected = {"classify", "ssi", "analytics", "linkage", "dossier", "evidence", "entity-extract", "ingest-retry"}
        assert expected == set(tasks.keys())

    def test_tasks_have_required_fields(self):
        tasks = all_tasks()
        for name, task in tasks.items():
            assert task.name == name
            assert task.description
            assert callable(task.run_fn)
            assert callable(task.pending_count_fn)
            assert task.lock_ttl_seconds > 0
