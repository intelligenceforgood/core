"""Add ssi_guidance_commands table for cloud analyst guidance relay.

Phase 3C of the SSI Case Enrichment & Live Monitor plan enables
bidirectional guidance commands between analysts and SSI investigations
in cloud deployments.  Analysts submit commands via the UI which are
stored in this table; SSI polls for pending commands and feeds them to
the running investigation's EventBus.

Revision ID: 20260303_02
Revises: 20260303_01
Create Date: 2026-03-03

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "20260303_02"
down_revision: str | None = "20260303_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the ssi_guidance_commands table."""
    conn = op.get_bind()
    insp = inspect(conn)
    existing_tables = insp.get_table_names()

    if "ssi_guidance_commands" not in existing_tables:
        op.create_table(
            "ssi_guidance_commands",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column(
                "scan_id",
                sa.String(length=64),
                sa.ForeignKey("site_scans.scan_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("action", sa.Text(), nullable=False),
            sa.Column("value", sa.Text(), nullable=True, default=""),
            sa.Column("reason", sa.Text(), nullable=True, default=""),
            sa.Column("acknowledged", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
        op.create_index("idx_ssi_guidance_scan_id", "ssi_guidance_commands", ["scan_id"])
        op.create_index(
            "idx_ssi_guidance_pending",
            "ssi_guidance_commands",
            ["scan_id", "acknowledged", "created_at"],
        )


def downgrade() -> None:
    """Drop the ssi_guidance_commands table."""
    op.drop_index("idx_ssi_guidance_pending", table_name="ssi_guidance_commands")
    op.drop_index("idx_ssi_guidance_scan_id", table_name="ssi_guidance_commands")
    op.drop_table("ssi_guidance_commands")
