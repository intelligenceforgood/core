"""Add analyst_labels table for ML training data collection.

Stores explicit analyst label assignments for cases, used as ground
truth for supervised ML model training.  Each row records which analyst
applied which label code to which case along a specific taxonomy axis.

Revision ID: 20260321_01
Revises: 20260318_01
Create Date: 2026-03-21

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "20260321_01"
down_revision: str | None = "20260318_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the analyst_labels table and its indexes."""
    conn = op.get_bind()
    insp = inspect(conn)
    existing_tables = insp.get_table_names()

    if "analyst_labels" not in existing_tables:
        op.create_table(
            "analyst_labels",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("case_id", sa.String(length=64), sa.ForeignKey("cases.case_id"), nullable=False, index=True),
            sa.Column("axis", sa.String(length=128), nullable=False),
            sa.Column("label_code", sa.String(length=128), nullable=False),
            sa.Column("analyst_id", sa.String(length=128), nullable=False),
            sa.Column("confidence", sa.Float(), server_default="1.0"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
        op.create_index(
            "ix_analyst_labels_case_axis",
            "analyst_labels",
            ["case_id", "axis"],
        )


def downgrade() -> None:
    """Drop the analyst_labels table."""
    conn = op.get_bind()
    insp = inspect(conn)
    if "analyst_labels" in insp.get_table_names():
        op.drop_index("ix_analyst_labels_case_axis", table_name="analyst_labels")
        op.drop_table("analyst_labels")
