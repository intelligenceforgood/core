"""Add taxonomy_rollup to campaigns.

Revision ID: 20260106_01
Revises: 20260104_01
Create Date: 2026-01-06 00:00:00.000000

"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260106_01"
down_revision: str | None = "20260104_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.add_column("campaigns", sa.Column("taxonomy_rollup", JSON_TYPE, server_default=sa.text("'[]'")))


def downgrade() -> None:
    op.drop_column("campaigns", "taxonomy_rollup")
