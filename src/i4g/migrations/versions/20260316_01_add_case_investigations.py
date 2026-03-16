"""Add case_investigations table and site_scans.normalized_url column.

Introduces the ``case_investigations`` join table that supports many-to-many
linking between cases and SSI investigations.  Also adds a ``normalized_url``
column to ``site_scans`` for URL deduplication queries.

Revision ID: 20260316_01
Revises: 20260315_01
Create Date: 2026-03-16

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "20260316_01"
down_revision: str | None = "20260315_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(insp: sa.engine.Inspector, name: str) -> bool:
    """Return True if the named table already exists."""
    return name in insp.get_table_names()


def _column_exists(insp: sa.engine.Inspector, table: str, column: str) -> bool:
    """Return True if the named column exists on the table."""
    if not _table_exists(insp, table):
        return False
    columns = {c["name"] for c in insp.get_columns(table)}
    return column in columns


def upgrade() -> None:
    """Create case_investigations table and add normalized_url to site_scans."""
    conn = op.get_bind()
    insp = inspect(conn)

    # --- case_investigations ---
    if not _table_exists(insp, "case_investigations"):
        op.create_table(
            "case_investigations",
            sa.Column("case_id", sa.Text(), nullable=False),
            sa.Column("scan_id", sa.String(length=64), nullable=False),
            sa.Column("trigger_type", sa.Text(), nullable=False, server_default="manual"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.PrimaryKeyConstraint("case_id", "scan_id"),
            sa.ForeignKeyConstraint(["case_id"], ["cases.case_id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["scan_id"], ["site_scans.scan_id"], ondelete="CASCADE"),
        )
        op.create_index("idx_case_investigations_scan_id", "case_investigations", ["scan_id"])
        op.create_index("idx_case_investigations_trigger_type", "case_investigations", ["trigger_type"])

    # --- site_scans.normalized_url ---
    if not _column_exists(insp, "site_scans", "normalized_url"):
        op.add_column("site_scans", sa.Column("normalized_url", sa.Text(), nullable=True))
        op.create_index(
            "idx_site_scans_normalized_url",
            "site_scans",
            ["normalized_url", "status", "completed_at"],
        )


def downgrade() -> None:
    """Drop case_investigations table and normalized_url column."""
    conn = op.get_bind()
    insp = inspect(conn)

    # Drop normalized_url column and index
    if _column_exists(insp, "site_scans", "normalized_url"):
        op.drop_index("idx_site_scans_normalized_url", table_name="site_scans")
        op.drop_column("site_scans", "normalized_url")

    # Drop case_investigations table
    if _table_exists(insp, "case_investigations"):
        op.drop_table("case_investigations")
