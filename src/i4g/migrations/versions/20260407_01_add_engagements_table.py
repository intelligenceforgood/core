"""Add engagements table and cases.engagement_id FK.

Introduces the ``engagements`` table for bounded work periods (competitions,
exercises, semesters) and adds a nullable ``engagement_id`` foreign key on
``cases`` to associate cases with an engagement.

Revision ID: 20260407_01
Revises: 20260404_01
Create Date: 2026-04-07

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "20260407_01"
down_revision: str | None = "20260404_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Column type helpers (must match sql.py definitions)
UUID_TYPE = sa.String(length=64)
TIMESTAMP = sa.DateTime(timezone=True)
JSON_TYPE = sa.JSON()


def _index_exists(inspector: sa.Inspector, table: str, index_name: str) -> bool:
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    # 1. Create the engagements table (skip if already exists, e.g. from bootstrap)
    if not inspector.has_table("engagements"):
        op.create_table(
            "engagements",
            sa.Column("engagement_id", UUID_TYPE, primary_key=True),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
            sa.Column("starts_at", TIMESTAMP, nullable=True),
            sa.Column("ends_at", TIMESTAMP, nullable=True),
            sa.Column("created_by", sa.Text(), nullable=True),
            sa.Column("metadata", JSON_TYPE, nullable=True),
            sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
    if not _index_exists(inspector, "engagements", "idx_engagements_status"):
        op.create_index("idx_engagements_status", "engagements", ["status"])
    if not _index_exists(inspector, "engagements", "idx_engagements_starts_at"):
        op.create_index("idx_engagements_starts_at", "engagements", ["starts_at"])

    # 2. Add engagement_id FK to cases (skip column if already present)
    cases_cols = {c["name"] for c in inspector.get_columns("cases")}
    if "engagement_id" not in cases_cols:
        op.add_column(
            "cases",
            sa.Column("engagement_id", UUID_TYPE, nullable=True),
        )
        # ForeignKey constraint — use batch mode for SQLite compatibility
        with op.batch_alter_table("cases") as batch_op:
            batch_op.create_foreign_key(
                "fk_cases_engagement_id",
                "engagements",
                ["engagement_id"],
                ["engagement_id"],
                ondelete="SET NULL",
            )
    if not _index_exists(inspector, "cases", "idx_cases_engagement_id"):
        op.create_index("idx_cases_engagement_id", "cases", ["engagement_id"])


def downgrade() -> None:
    op.drop_index("idx_cases_engagement_id", table_name="cases")
    with op.batch_alter_table("cases") as batch_op:
        batch_op.drop_constraint("fk_cases_engagement_id", type_="foreignkey")
    op.drop_column("cases", "engagement_id")
    op.drop_index("idx_engagements_starts_at", table_name="engagements")
    op.drop_index("idx_engagements_status", table_name="engagements")
    op.drop_table("engagements")
