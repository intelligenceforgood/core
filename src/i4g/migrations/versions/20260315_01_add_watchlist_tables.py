"""Add watchlist_items and watchlist_alerts tables.

Sprint 5 defined watchlist_items and watchlist_alerts in the ORM
(sql.py) but no Alembic migration was created.  This backfills the
gap so the tables are created on cloud databases.

Revision ID: 20260315_01
Revises: 20260314_02
Create Date: 2026-03-15

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "20260315_01"
down_revision: str | None = "20260314_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(insp: sa.engine.Inspector, name: str) -> bool:
    """Return True if the named table already exists."""
    return name in insp.get_table_names()


def upgrade() -> None:
    """Create watchlist_items and watchlist_alerts tables."""
    conn = op.get_bind()
    insp = inspect(conn)

    # --- watchlist_items ---
    if not _table_exists(insp, "watchlist_items"):
        op.create_table(
            "watchlist_items",
            sa.Column("watchlist_id", sa.Text(), primary_key=True),
            sa.Column("entity_type", sa.Text(), nullable=False),
            sa.Column("canonical_value", sa.Text(), nullable=False),
            sa.Column("alert_on_new_case", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("alert_on_loss_increase", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("loss_threshold", sa.Numeric(precision=18, scale=2), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_by", sa.Text(), nullable=False, server_default="system"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
        op.create_index(
            "idx_watchlist_entity",
            "watchlist_items",
            ["entity_type", "canonical_value"],
            unique=True,
        )
        op.create_index("idx_watchlist_created_by", "watchlist_items", ["created_by"])

    # --- watchlist_alerts ---
    if not _table_exists(insp, "watchlist_alerts"):
        op.create_table(
            "watchlist_alerts",
            sa.Column("alert_id", sa.Text(), primary_key=True),
            sa.Column("watchlist_id", sa.Text(), nullable=False),
            sa.Column("alert_type", sa.Text(), nullable=False),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("data", sa.JSON(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
        op.create_index("idx_watchlist_alerts_watchlist", "watchlist_alerts", ["watchlist_id"])
        op.create_index("idx_watchlist_alerts_unread", "watchlist_alerts", ["is_read"])


def downgrade() -> None:
    """Drop watchlist tables."""
    conn = op.get_bind()
    insp = inspect(conn)

    if _table_exists(insp, "watchlist_alerts"):
        op.drop_table("watchlist_alerts")
    if _table_exists(insp, "watchlist_items"):
        op.drop_table("watchlist_items")
