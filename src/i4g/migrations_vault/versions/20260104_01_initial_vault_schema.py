"""Initial vault schema.

Revision ID: 20260104_01
Revises:
Create Date: 2026-01-04 13:30:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260104_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the migration."""

    # PII Tokens Table
    op.create_table(
        "pii_tokens",
        sa.Column("token", sa.String(length=20), nullable=False),
        sa.Column("prefix", sa.String(length=3), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("normalized_value", sa.Text(), nullable=False),
        sa.Column("canonical_value", sa.Text(), nullable=True),
        sa.Column("encrypted_value", sa.LargeBinary(), nullable=True),
        sa.Column("pepper_version", sa.String(length=10), nullable=False),
        sa.Column("detector", sa.String(length=50), nullable=True),
        sa.Column("case_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.PrimaryKeyConstraint("token"),
    )
    op.create_index("idx_pii_tokens_digest", "pii_tokens", ["digest"], unique=False)
    op.create_index("idx_pii_tokens_prefix", "pii_tokens", ["prefix"], unique=False)

    # Audit Log Table (Missing from previous migration)
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("token", sa.Text(), nullable=True),
        sa.Column("prefix", sa.Text(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("case_id", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_audit_log_token", "audit_log", ["token"], unique=False)
    op.create_index("idx_audit_log_actor", "audit_log", ["actor"], unique=False)


def downgrade() -> None:
    """Revert the migration."""
    op.drop_index("idx_audit_log_actor", table_name="audit_log")
    op.drop_index("idx_audit_log_token", table_name="audit_log")
    op.drop_table("audit_log")

    op.drop_index("idx_pii_tokens_prefix", table_name="pii_tokens")
    op.drop_index("idx_pii_tokens_digest", table_name="pii_tokens")
    op.drop_table("pii_tokens")
