"""Add resolved_at and purged_at columns to cases table.

These columns were defined in the SQLAlchemy model but never migrated.
resolved_at is used by analytics_aggregation (platform_kpis) and retention.
purged_at is used by the retention service.

Revision ID: 20260330_01
Revises: 20260329_02
Create Date: 2026-03-30

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "20260330_01"
down_revision: str | None = "20260329_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add resolved_at and purged_at columns to cases."""
    conn = op.get_bind()
    insp = inspect(conn)
    existing = {col["name"] for col in insp.get_columns("cases")}

    if "resolved_at" not in existing:
        op.add_column("cases", sa.Column("resolved_at", sa.DateTime(), nullable=True))

    if "purged_at" not in existing:
        op.add_column("cases", sa.Column("purged_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Remove resolved_at and purged_at columns from cases."""
    op.drop_column("cases", "purged_at")
    op.drop_column("cases", "resolved_at")
