"""Add TIFAP Sprint 4 columns and annotations table.

- S4-01: Add taken_down_at TIMESTAMP to site_scans
- S4-02: Add lea_referred_at, lea_agency, lea_case_number to cases
- S4-03: Add victim_age_range TEXT to intake_records
- S4-04: Split contact_handle into contact_channel + contact_identifier
         on intake_records (add new columns, keep original for backcompat)
- S4-15: Create annotations table for analyst notes on entities,
         indicators, and campaigns

Revision ID: 20260313_01
Revises: 20260312_01
Create Date: 2026-03-13

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "20260313_01"
down_revision: str | None = "20260312_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(insp: sa.engine.Inspector, name: str) -> bool:
    """Return True if the named table already exists."""
    return name in insp.get_table_names()


def _column_exists(insp: sa.engine.Inspector, table: str, column: str) -> bool:
    """Return True if the named column already exists on the table."""
    if not _table_exists(insp, table):
        return False
    columns = {col["name"] for col in insp.get_columns(table)}
    return column in columns


def upgrade() -> None:
    """Add Sprint 4 columns and annotations table."""
    conn = op.get_bind()
    insp = inspect(conn)

    # --- S4-01: site_scans.taken_down_at ---
    if _table_exists(insp, "site_scans") and not _column_exists(insp, "site_scans", "taken_down_at"):
        op.add_column("site_scans", sa.Column("taken_down_at", sa.DateTime(timezone=True), nullable=True))

    # --- S4-02: cases LEA referral columns ---
    if _table_exists(insp, "cases"):
        if not _column_exists(insp, "cases", "lea_referred_at"):
            op.add_column("cases", sa.Column("lea_referred_at", sa.DateTime(timezone=True), nullable=True))
        if not _column_exists(insp, "cases", "lea_agency"):
            op.add_column("cases", sa.Column("lea_agency", sa.Text(), nullable=True))
        if not _column_exists(insp, "cases", "lea_case_number"):
            op.add_column("cases", sa.Column("lea_case_number", sa.Text(), nullable=True))

    # --- S4-03: intake_records.victim_age_range ---
    if _table_exists(insp, "intake_records") and not _column_exists(insp, "intake_records", "victim_age_range"):
        op.add_column("intake_records", sa.Column("victim_age_range", sa.Text(), nullable=True))

    # --- S4-04: intake_records contact_channel + contact_identifier ---
    # Keep contact_handle for backwards compatibility; add two new columns
    # that split the handle into channel (e.g. "telegram", "whatsapp")
    # and identifier (the actual handle value).
    if _table_exists(insp, "intake_records"):
        if not _column_exists(insp, "intake_records", "contact_channel"):
            op.add_column("intake_records", sa.Column("contact_channel", sa.Text(), nullable=True))
        if not _column_exists(insp, "intake_records", "contact_identifier"):
            op.add_column("intake_records", sa.Column("contact_identifier", sa.Text(), nullable=True))

    # --- S4-15: annotations table ---
    if not _table_exists(insp, "annotations"):
        op.create_table(
            "annotations",
            sa.Column("annotation_id", sa.String(length=64), primary_key=True),
            sa.Column("target_type", sa.Text(), nullable=False),  # entity | indicator | campaign | case
            sa.Column("target_id", sa.Text(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("author", sa.Text(), nullable=False, server_default="system"),
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
        op.create_index("idx_annotations_target", "annotations", ["target_type", "target_id"])
        op.create_index("idx_annotations_author", "annotations", ["author"])


def downgrade() -> None:
    """Remove Sprint 4 columns and annotations table."""
    conn = op.get_bind()
    insp = inspect(conn)

    if _table_exists(insp, "annotations"):
        op.drop_table("annotations")

    if _table_exists(insp, "intake_records"):
        if _column_exists(insp, "intake_records", "contact_identifier"):
            op.drop_column("intake_records", "contact_identifier")
        if _column_exists(insp, "intake_records", "contact_channel"):
            op.drop_column("intake_records", "contact_channel")
        if _column_exists(insp, "intake_records", "victim_age_range"):
            op.drop_column("intake_records", "victim_age_range")

    if _table_exists(insp, "cases"):
        for col in ("lea_case_number", "lea_agency", "lea_referred_at"):
            if _column_exists(insp, "cases", col):
                op.drop_column("cases", col)

    if _table_exists(insp, "site_scans") and _column_exists(insp, "site_scans", "taken_down_at"):
        op.drop_column("site_scans", "taken_down_at")
