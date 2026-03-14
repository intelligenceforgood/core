"""Add taken_down_at column to entity_stats.

The entity_stats SQLAlchemy model already declares this column but
the original create-table migration (20260312_01) omitted it.
This migration backfills the gap.

Revision ID: 20260314_02
Revises: 20260314_01
Create Date: 2026-03-14

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "20260314_02"
down_revision: str | None = "20260314_01"
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
    """Add taken_down_at to entity_stats."""
    conn = op.get_bind()
    insp = inspect(conn)

    if _table_exists(insp, "entity_stats") and not _column_exists(insp, "entity_stats", "taken_down_at"):
        op.add_column("entity_stats", sa.Column("taken_down_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Remove taken_down_at from entity_stats."""
    conn = op.get_bind()
    insp = inspect(conn)

    if _column_exists(insp, "entity_stats", "taken_down_at"):
        op.drop_column("entity_stats", "taken_down_at")
