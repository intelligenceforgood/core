"""Add audit_log table for victim-contact access tracking.

Moves the ``audit_log`` table from the retired PII vault database into
the main application database.  The table records access to decrypted
victim-contact fields and other sensitive operations for compliance
auditing.

Revision ID: 20260318_01
Revises: 20260317_01
Create Date: 2026-03-18

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260318_01"
down_revision: str | None = "20260317_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the audit_log table and its indexes."""
    conn = op.get_bind()
    insp = inspect(conn)
    existing_tables = insp.get_table_names()

    if "audit_log" not in existing_tables:
        op.create_table(
            "audit_log",
            sa.Column("audit_id", sa.String(length=64), primary_key=True),
            sa.Column("actor", sa.Text(), nullable=False),
            sa.Column("action", sa.Text(), nullable=False),
            sa.Column("resource_type", sa.Text(), nullable=False),
            sa.Column("resource_id", sa.Text(), nullable=False),
            sa.Column(
                "detail",
                sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
                nullable=True,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
        op.create_index("idx_audit_log_actor", "audit_log", ["actor"])
        op.create_index("idx_audit_log_resource", "audit_log", ["resource_type", "resource_id"])
        op.create_index("idx_audit_log_created", "audit_log", ["created_at"])


def downgrade() -> None:
    """Drop the audit_log table."""
    conn = op.get_bind()
    insp = inspect(conn)
    if "audit_log" in insp.get_table_names():
        op.drop_index("idx_audit_log_created", table_name="audit_log")
        op.drop_index("idx_audit_log_resource", table_name="audit_log")
        op.drop_index("idx_audit_log_actor", table_name="audit_log")
        op.drop_table("audit_log")
