"""Add ecx_submissions table for Phase 2 eCrimeX indicator submission tracking.

Phase 2 of the ECX integration plan adds the ability to submit investigated
indicators (phishing URLs, crypto wallets, malicious domains / IPs) to the
eCrimeX platform.  This table tracks each submission, its status through the
review / approval pipeline, and the record ID assigned by eCX on success.

Revision ID: 20260305_01
Revises: 20260303_02
Create Date: 2026-03-05

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "20260305_01"
down_revision: str | None = "20260303_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the ecx_submissions table and its indexes."""
    conn = op.get_bind()
    insp = inspect(conn)
    existing_tables = insp.get_table_names()

    if "ecx_submissions" not in existing_tables:
        op.create_table(
            "ecx_submissions",
            sa.Column("submission_id", sa.String(length=64), primary_key=True),
            sa.Column("scan_id", sa.String(length=64), nullable=True),
            sa.Column("case_id", sa.Text(), nullable=True),
            # Module: phish | malicious-domain | malicious-ip | cryptocurrency-addresses
            sa.Column("ecx_module", sa.Text(), nullable=False),
            # Record ID assigned by eCX on a successful POST (null until submitted)
            sa.Column("ecx_record_id", sa.Integer(), nullable=True),
            sa.Column("submitted_value", sa.Text(), nullable=False),
            sa.Column("confidence", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("release_label", sa.Text(), nullable=False, server_default=""),
            # Status: pending | queued | submitted | updated | failed | rejected | retracted
            sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
            # "auto" for pipeline submissions or an analyst identifier
            sa.Column("submitted_by", sa.Text(), nullable=False, server_default=""),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
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

        op.create_index("idx_ecx_submissions_scan_id", "ecx_submissions", ["scan_id"])
        op.create_index("idx_ecx_submissions_case_id", "ecx_submissions", ["case_id"])
        op.create_index("idx_ecx_submissions_status", "ecx_submissions", ["status"])
        op.create_index("idx_ecx_submissions_module", "ecx_submissions", ["ecx_module"])


def downgrade() -> None:
    """Drop the ecx_submissions table and its indexes."""
    conn = op.get_bind()
    insp = inspect(conn)
    existing_tables = insp.get_table_names()

    if "ecx_submissions" in existing_tables:
        op.drop_index("idx_ecx_submissions_module", table_name="ecx_submissions")
        op.drop_index("idx_ecx_submissions_status", table_name="ecx_submissions")
        op.drop_index("idx_ecx_submissions_case_id", table_name="ecx_submissions")
        op.drop_index("idx_ecx_submissions_scan_id", table_name="ecx_submissions")
        op.drop_table("ecx_submissions")
