"""Backfill status queries — introspect pending work and lock state.

Provides functions used by ``i4g backfill status`` and the daemon to
determine which tasks have items waiting to be processed.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa

from i4g.store import sql as sql_schema
from i4g.store.sql import session_factory as build_sql_session_factory

logger = logging.getLogger(__name__)


def get_active_locks() -> list[dict[str, Any]]:
    """Return currently held (non-expired) locks."""
    sf = build_sql_session_factory()
    now = datetime.now(UTC)
    with sf() as session:
        rows = session.execute(
            sa.select(sql_schema.backfill_locks).where(sql_schema.backfill_locks.c.expires_at >= now)
        ).fetchall()
        return [
            {
                "task_name": row.task_name,
                "holder_id": row.holder_id,
                "acquired_at": row.acquired_at.isoformat() if row.acquired_at else None,
                "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            }
            for row in rows
        ]
