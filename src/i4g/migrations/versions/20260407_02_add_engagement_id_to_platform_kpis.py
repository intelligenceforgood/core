"""Add engagement_id to platform_kpis for per-engagement KPI breakdowns.

Adds a nullable ``engagement_id`` column to ``platform_kpis`` and updates the
primary key to include it.  The ``__global__`` sentinel value represents the
aggregate row across all engagements; per-engagement rows carry the actual
engagement UUID.

Revision ID: 20260407_02
Revises: 20260407_01
Create Date: 2026-04-07

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "20260407_02"
down_revision: str | None = "20260407_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID_TYPE = sa.String(length=64)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    cols = {c["name"] for c in inspector.get_columns("platform_kpis")}
    if "engagement_id" not in cols:
        # 1. Add engagement_id column (nullable initially)
        op.add_column(
            "platform_kpis",
            sa.Column("engagement_id", UUID_TYPE, nullable=True),
        )

        # 2. Backfill existing rows with the __global__ sentinel
        op.execute("UPDATE platform_kpis SET engagement_id = '__global__' WHERE engagement_id IS NULL")

        # 3. Rebuild the primary key to include engagement_id
        with op.batch_alter_table("platform_kpis") as batch_op:
            batch_op.drop_constraint("pk_platform_kpis", type_="primary")
            batch_op.create_primary_key(
                "pk_platform_kpis",
                ["period_type", "period_start", "engagement_id"],
            )

        # 4. Index for engagement-scoped queries
        op.create_index("idx_platform_kpis_engagement_id", "platform_kpis", ["engagement_id"])


def downgrade() -> None:
    # Remove per-engagement rows, leaving only __global__
    op.execute("DELETE FROM platform_kpis WHERE engagement_id != '__global__'")

    with op.batch_alter_table("platform_kpis") as batch_op:
        batch_op.drop_constraint("pk_platform_kpis", type_="primary")
        batch_op.create_primary_key(
            "pk_platform_kpis",
            ["period_type", "period_start"],
        )

    op.drop_index("idx_platform_kpis_engagement_id", table_name="platform_kpis")
    op.drop_column("platform_kpis", "engagement_id")
