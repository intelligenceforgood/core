"""Add ecx_polling_state table for Phase 3 eCrimeX inbound polling.

Phase 3 of the ECX integration plan adds inbound polling from the
eCrimeX data clearinghouse.  This table tracks the per-module polling
cursor (last_polled_id) so each poll cycle only fetches new records.

Revision ID: 20260306_01
Revises: 20260305_01
Create Date: 2026-03-06

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "20260306_01"
down_revision: str | None = "20260305_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the ecx_polling_state table."""
    conn = op.get_bind()
    insp = inspect(conn)
    existing_tables = insp.get_table_names()

    if "ecx_polling_state" not in existing_tables:
        op.create_table(
            "ecx_polling_state",
            # Primary key: module name (phish | malicious-domain | malicious-ip | cryptocurrency-addresses)
            sa.Column("module", sa.Text(), primary_key=True),
            sa.Column("last_polled_id", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("records_found", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("errors", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )


def downgrade() -> None:
    """Drop the ecx_polling_state table."""
    conn = op.get_bind()
    insp = inspect(conn)
    existing_tables = insp.get_table_names()

    if "ecx_polling_state" in existing_tables:
        op.drop_table("ecx_polling_state")
