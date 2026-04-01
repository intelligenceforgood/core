"""Add partner_api_keys and partner_feed_audit tables.

These tables were defined in sql.py but never added to a migration.
partner_api_keys stores hashed API keys issued to data-feed partners.
partner_feed_audit is the per-request access log for the partner feed API.

Revision ID: 20260331_01
Revises: 20260330_01
Create Date: 2026-03-31

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "20260331_01"
down_revision: str | None = "20260330_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create partner_api_keys and partner_feed_audit tables if they don't exist."""
    conn = op.get_bind()
    insp = inspect(conn)
    existing = set(insp.get_table_names())

    if "partner_api_keys" not in existing:
        op.create_table(
            "partner_api_keys",
            sa.Column("key_id", sa.String(length=64), primary_key=True),
            sa.Column("partner_name", sa.Text(), nullable=False),
            sa.Column("key_hash", sa.Text(), nullable=False),
            sa.Column("key_prefix", sa.String(length=8), nullable=False),
            sa.Column("scopes", sa.JSON(), nullable=True),
            sa.Column("rate_limit_per_minute", sa.Integer(), nullable=False, server_default=sa.text("60")),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_by", sa.Text(), nullable=False),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
        op.create_index("idx_partner_keys_prefix", "partner_api_keys", ["key_prefix"])
        op.create_index("idx_partner_keys_active", "partner_api_keys", ["is_active"])

    if "partner_feed_audit" not in existing:
        op.create_table(
            "partner_feed_audit",
            sa.Column("audit_id", sa.String(length=64), primary_key=True),
            sa.Column("key_id", sa.String(length=64), nullable=False),
            sa.Column("partner_name", sa.Text(), nullable=False),
            sa.Column("endpoint", sa.Text(), nullable=False),
            sa.Column("method", sa.Text(), nullable=False),
            sa.Column("query_params", sa.JSON(), nullable=True),
            sa.Column("result_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("response_code", sa.Integer(), nullable=False),
            sa.Column("ip_address", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
        op.create_index("idx_partner_audit_key", "partner_feed_audit", ["key_id"])
        op.create_index("idx_partner_audit_created", "partner_feed_audit", ["created_at"])


def downgrade() -> None:
    """Drop partner_feed_audit and partner_api_keys tables."""
    op.drop_index("idx_partner_audit_created", table_name="partner_feed_audit")
    op.drop_index("idx_partner_audit_key", table_name="partner_feed_audit")
    op.drop_table("partner_feed_audit")

    op.drop_index("idx_partner_keys_active", table_name="partner_api_keys")
    op.drop_index("idx_partner_keys_prefix", table_name="partner_api_keys")
    op.drop_table("partner_api_keys")
