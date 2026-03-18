"""Add ecx_enrichments table for eCrimeX enrichment cache.

Adds the ``ecx_enrichments`` table which caches eCrimeX enrichment hits
per investigation.  Each row stores the full eCX record JSON so cached
results can be returned without repeating API calls.

The table was previously auto-created by ``ScanStore.__init__()`` via
``METADATA.create_all()`` on SQLite, but the PostgreSQL auto-create path
only fired when the four core SSI tables were missing.  If those tables
already existed (via migration ``20260221_01``), ``ecx_enrichments`` was
never created — causing the ``relation "ecx_enrichments" does not exist``
error at runtime.

Revision ID: 20260317_01
Revises: 20260316_01
Create Date: 2026-03-17

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260317_01"
down_revision: str | None = "20260316_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the ecx_enrichments table and its indexes."""
    conn = op.get_bind()
    insp = inspect(conn)
    existing_tables = insp.get_table_names()

    if "ecx_enrichments" not in existing_tables:
        op.create_table(
            "ecx_enrichments",
            sa.Column("enrichment_id", sa.String(length=64), primary_key=True),
            sa.Column("scan_id", sa.String(length=64), nullable=False),
            sa.Column("query_module", sa.Text(), nullable=False),
            sa.Column("query_value", sa.Text(), nullable=False),
            sa.Column("ecx_record_id", sa.Integer(), nullable=True),
            sa.Column(
                "ecx_data",
                sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
                nullable=True,
            ),
            sa.Column("confidence", sa.Integer(), nullable=True),
            sa.Column(
                "queried_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column("cache_expires_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("idx_ecx_enrichments_scan_id", "ecx_enrichments", ["scan_id"])
        op.create_index("idx_ecx_enrichments_query", "ecx_enrichments", ["query_module", "query_value"])


def downgrade() -> None:
    """Drop the ecx_enrichments table."""
    conn = op.get_bind()
    insp = inspect(conn)
    if "ecx_enrichments" in insp.get_table_names():
        op.drop_index("idx_ecx_enrichments_query", table_name="ecx_enrichments")
        op.drop_index("idx_ecx_enrichments_scan_id", table_name="ecx_enrichments")
        op.drop_table("ecx_enrichments")
