"""fix_api_keys_columns

Revision ID: 20260730_01
Revises: 20260729_01
Create Date: 2026-07-30

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "20260730_01"
down_revision: str | None = "20260729_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    tables = set(insp.get_table_names())

    if "api_keys" in tables:
        columns = {col["name"] for col in insp.get_columns("api_keys")}
        with op.batch_alter_table("api_keys") as batch_op:
            if "name" in columns:
                batch_op.alter_column("name", existing_type=sa.Text(), nullable=True)
            if "partner_name" not in columns:
                batch_op.add_column(sa.Column("partner_name", sa.Text(), nullable=True))
            if "scopes" not in columns:
                batch_op.add_column(sa.Column("scopes", sa.JSON(), nullable=True))
            if "rate_limit_per_minute" not in columns:
                batch_op.add_column(
                    sa.Column("rate_limit_per_minute", sa.Integer(), nullable=False, server_default=sa.text("60"))
                )
            if "key_type" not in columns:
                batch_op.add_column(sa.Column("key_type", sa.Text(), nullable=False, server_default="partner"))
            if "description" not in columns:
                batch_op.add_column(sa.Column("description", sa.Text(), nullable=True))
            if "owner_email" not in columns:
                batch_op.add_column(sa.Column("owner_email", sa.Text(), nullable=True))


def downgrade() -> None:
    pass
