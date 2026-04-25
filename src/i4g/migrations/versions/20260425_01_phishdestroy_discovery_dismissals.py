"""PhishDestroy Sprint 1 Phase E1: add dismissed_at + dismiss_reason to domain_discoveries.

Revision ID: 20260425_01
Revises: 20260424_01
Create Date: 2026-04-25

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "20260425_01"
down_revision: str | None = "20260424_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Column type helpers (must match sql.py definitions)
TIMESTAMP = sa.DateTime(timezone=True)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    existing_cols = [c["name"] for c in inspector.get_columns("domain_discoveries")]

    if "dismissed_at" not in existing_cols:
        op.add_column("domain_discoveries", sa.Column("dismissed_at", TIMESTAMP, nullable=True))

    if "dismiss_reason" not in existing_cols:
        op.add_column("domain_discoveries", sa.Column("dismiss_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    existing_cols = [c["name"] for c in inspector.get_columns("domain_discoveries")]

    with op.batch_alter_table("domain_discoveries") as batch_op:
        if "dismiss_reason" in existing_cols:
            batch_op.drop_column("dismiss_reason")
        if "dismissed_at" in existing_cols:
            batch_op.drop_column("dismissed_at")
