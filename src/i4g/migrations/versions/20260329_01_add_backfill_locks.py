"""Add backfill_locks table for distributed coordination.

Provides a lightweight advisory-lock mechanism for backfill and sweeper
jobs.  Each row represents a named task lock with an expiry timestamp.
Concurrent workers attempt INSERT-or-skip to acquire the lock and
DELETE to release it.

Works on both SQLite (local dev) and PostgreSQL (Cloud SQL).

Revision ID: 20260329_01
Revises: 20260321_02
Create Date: 2026-03-29

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "20260329_01"
down_revision: str | None = "20260321_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the backfill_locks table."""
    conn = op.get_bind()
    insp = inspect(conn)
    existing_tables = insp.get_table_names()

    if "backfill_locks" not in existing_tables:
        op.create_table(
            "backfill_locks",
            sa.Column("task_name", sa.String(length=128), primary_key=True),
            sa.Column("holder_id", sa.String(length=128), nullable=False),
            sa.Column(
                "acquired_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        )


def downgrade() -> None:
    """Drop the backfill_locks table."""
    conn = op.get_bind()
    insp = inspect(conn)
    if "backfill_locks" in insp.get_table_names():
        op.drop_table("backfill_locks")
