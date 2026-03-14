"""Add failure tracking columns to scheduled_reports.

- S6-H3: Add consecutive_failures INT (default 0) and last_error TEXT
  to scheduled_reports so the scheduled-reports job can advance
  last_run_at on failure, track errors, and auto-deactivate after
  N consecutive failures.

Revision ID: 20260314_01
Revises: 20260313_01
Create Date: 2026-03-14

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "20260314_01"
down_revision: str | None = "20260313_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(insp: sa.engine.Inspector, name: str) -> bool:
    """Return True if the named table already exists."""
    return name in insp.get_table_names()


def _column_exists(insp: sa.engine.Inspector, table: str, column: str) -> bool:
    """Return True if the named column already exists on the table."""
    if not _table_exists(insp, table):
        return False
    columns = {col["name"] for col in insp.get_columns(table)}
    return column in columns


def upgrade() -> None:
    """Add failure tracking columns to scheduled_reports."""
    conn = op.get_bind()
    insp = inspect(conn)

    if _table_exists(insp, "scheduled_reports"):
        if not _column_exists(insp, "scheduled_reports", "consecutive_failures"):
            op.add_column(
                "scheduled_reports",
                sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default=sa.text("0")),
            )
        if not _column_exists(insp, "scheduled_reports", "last_error"):
            op.add_column(
                "scheduled_reports",
                sa.Column("last_error", sa.Text(), nullable=True),
            )


def downgrade() -> None:
    """Remove failure tracking columns from scheduled_reports."""
    conn = op.get_bind()
    insp = inspect(conn)

    if _table_exists(insp, "scheduled_reports"):
        if _column_exists(insp, "scheduled_reports", "last_error"):
            op.drop_column("scheduled_reports", "last_error")
        if _column_exists(insp, "scheduled_reports", "consecutive_failures"):
            op.drop_column("scheduled_reports", "consecutive_failures")
