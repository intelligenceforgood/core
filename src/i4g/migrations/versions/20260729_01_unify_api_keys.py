"""unify_api_keys

Revision ID: 20260729_01
Revises: 20260430_01
Create Date: 2026-07-29

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "20260729_01"
down_revision: str | None = "20260430_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    tables = set(insp.get_table_names())

    if "partner_api_keys" in tables and "api_keys" not in tables:
        op.rename_table("partner_api_keys", "api_keys")
        try:
            op.rename_index("partner_api_keys", "idx_partner_keys_prefix", "idx_api_keys_prefix")
            op.rename_index("partner_api_keys", "idx_partner_keys_active", "idx_api_keys_active")
        except Exception:
            pass
        tables.remove("partner_api_keys")
        tables.add("api_keys")
    elif "api_keys" not in tables:
        op.create_table(
            "api_keys",
            sa.Column("key_id", sa.String(length=64), primary_key=True),
            sa.Column("partner_name", sa.Text(), nullable=True),
            sa.Column("key_hash", sa.Text(), nullable=False),
            sa.Column("key_prefix", sa.String(length=64), nullable=False),
            sa.Column("scopes", sa.JSON(), nullable=True),
            sa.Column("rate_limit_per_minute", sa.Integer(), nullable=False, server_default=sa.text("60")),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_by", sa.Text(), nullable=False, server_default="system"),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
        op.create_index("idx_api_keys_prefix", "api_keys", ["key_prefix"])
        op.create_index("idx_api_keys_active", "api_keys", ["is_active"])
        tables.add("api_keys")

    # Add new columns and adjust nullable/type using batch_alter_table for SQLite compatibility
    columns = {col["name"] for col in insp.get_columns("api_keys")}
    with op.batch_alter_table("api_keys") as batch_op:
        if "key_type" not in columns:
            batch_op.add_column(sa.Column("key_type", sa.Text(), nullable=False, server_default="partner"))
        if "description" not in columns:
            batch_op.add_column(sa.Column("description", sa.Text(), nullable=True))
        if "owner_email" not in columns:
            batch_op.add_column(sa.Column("owner_email", sa.Text(), nullable=True))
        if "created_by" not in columns:
            batch_op.add_column(sa.Column("created_by", sa.Text(), nullable=False, server_default="system"))
        if "partner_name" in columns:
            batch_op.alter_column("partner_name", existing_type=sa.Text(), nullable=True)
        else:
            batch_op.add_column(sa.Column("partner_name", sa.Text(), nullable=True))
        if "scopes" not in columns:
            batch_op.add_column(sa.Column("scopes", sa.JSON(), nullable=True))
        if "rate_limit_per_minute" not in columns:
            batch_op.add_column(
                sa.Column("rate_limit_per_minute", sa.Integer(), nullable=False, server_default=sa.text("60"))
            )
        batch_op.alter_column(
            "key_prefix", existing_type=sa.String(length=12), type_=sa.String(length=64), nullable=False
        )

    # Add unique index on key_hash
    indices = {idx["name"] for idx in insp.get_indexes("api_keys")}
    if "uq_api_keys_key_hash" not in indices:
        op.create_index("uq_api_keys_key_hash", "api_keys", ["key_hash"], unique=True)

    # Backfill owner_email from created_by for existing rows
    if "created_by" in columns or "created_by" not in columns:  # created_by is guaranteed now
        op.execute("UPDATE api_keys SET owner_email = created_by WHERE owner_email IS NULL AND created_by IS NOT NULL")


def downgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    tables = set(insp.get_table_names())

    if "_alembic_tmp_api_keys" in tables:
        op.execute("DROP TABLE IF EXISTS _alembic_tmp_api_keys")

    if "api_keys" in tables:
        indices = {idx["name"] for idx in insp.get_indexes("api_keys")}
        if "uq_api_keys_key_hash" in indices:
            op.drop_index("uq_api_keys_key_hash", table_name="api_keys")
        if "idx_api_keys_owner_email" in indices:
            op.drop_index("idx_api_keys_owner_email", table_name="api_keys")
        if "idx_api_keys_key_type" in indices:
            op.drop_index("idx_api_keys_key_type", table_name="api_keys")

        columns = {col["name"] for col in insp.get_columns("api_keys")}
        with op.batch_alter_table("api_keys") as batch_op:
            if "owner_email" in columns:
                batch_op.drop_column("owner_email")
            if "description" in columns:
                batch_op.drop_column("description")
            if "key_type" in columns:
                batch_op.drop_column("key_type")

        if "partner_api_keys" not in tables:
            op.rename_table("api_keys", "partner_api_keys")
            try:
                op.rename_index("partner_api_keys", "idx_api_keys_prefix", "idx_partner_keys_prefix")
                op.rename_index("partner_api_keys", "idx_api_keys_active", "idx_partner_keys_active")
            except Exception:
                pass
