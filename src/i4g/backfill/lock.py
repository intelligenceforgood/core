"""Database-backed advisory locks for backfill task coordination.

Each backfill task acquires a named lock before executing.  The lock is a
row in the ``backfill_locks`` table with an expiry timestamp.  If a
previous holder crashed without releasing, the lock is automatically
expired and can be re-acquired.

This works on both SQLite (local) and PostgreSQL (Cloud SQL) — no
advisory-lock extensions required.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import sqlalchemy as sa

from i4g.store import sql as sql_schema

if TYPE_CHECKING:
    from collections.abc import Generator

    from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    return datetime.now(UTC)


def acquire_lock(
    task_name: str,
    session: Session,
    *,
    ttl_seconds: int = 3600,
    holder_id: str | None = None,
) -> str | None:
    """Try to acquire the named lock.  Returns holder_id on success, None on contention.

    Expired locks are reaped automatically before the attempt.
    """
    holder = holder_id or f"{task_name}-{uuid.uuid4().hex[:8]}"
    now = _now_utc()
    table = sql_schema.backfill_locks

    # Reap expired locks
    session.execute(sa.delete(table).where(table.c.expires_at < now))

    # Check if lock is held
    existing = session.execute(sa.select(table.c.holder_id).where(table.c.task_name == task_name)).fetchone()
    if existing is not None:
        logger.info("Lock '%s' already held by %s — skipping", task_name, existing.holder_id)
        session.commit()
        return None

    # Insert lock row
    try:
        session.execute(
            sa.insert(table).values(
                task_name=task_name,
                holder_id=holder,
                acquired_at=now,
                expires_at=now + timedelta(seconds=ttl_seconds),
            )
        )
        session.commit()
        logger.debug("Acquired lock '%s' as %s (ttl=%ds)", task_name, holder, ttl_seconds)
        return holder
    except sa.exc.IntegrityError:
        session.rollback()
        logger.info("Lock '%s' contention (concurrent acquire) — skipping", task_name)
        return None


def release_lock(task_name: str, holder_id: str, session: Session) -> None:
    """Release the named lock if still held by this holder."""
    table = sql_schema.backfill_locks
    result = session.execute(sa.delete(table).where(table.c.task_name == task_name, table.c.holder_id == holder_id))
    session.commit()
    if result.rowcount:
        logger.debug("Released lock '%s' (holder=%s)", task_name, holder_id)
    else:
        logger.debug("Lock '%s' was already released or expired", task_name)


def refresh_lock(task_name: str, holder_id: str, session: Session, *, ttl_seconds: int = 3600) -> bool:
    """Extend the lock TTL.  Returns True if still held, False if lost."""
    table = sql_schema.backfill_locks
    now = _now_utc()
    result = session.execute(
        sa.update(table)
        .where(table.c.task_name == task_name, table.c.holder_id == holder_id)
        .values(expires_at=now + timedelta(seconds=ttl_seconds))
    )
    session.commit()
    return result.rowcount > 0


@contextmanager
def task_lock(
    task_name: str,
    sf: sessionmaker,
    *,
    ttl_seconds: int = 3600,
) -> Generator[str | None, None, None]:
    """Context manager that acquires the lock on entry and releases on exit.

    Yields the holder_id if acquired, or ``None`` if the lock is already held.
    Callers should check for ``None`` and skip work accordingly.

    Example::

        with task_lock("classify", sf) as holder:
            if holder is None:
                return  # another instance is running
            do_work()
    """
    with sf() as session:
        holder = acquire_lock(task_name, session, ttl_seconds=ttl_seconds)

    if holder is None:
        yield None
        return

    try:
        yield holder
    finally:
        with sf() as session:
            release_lock(task_name, holder, session)
