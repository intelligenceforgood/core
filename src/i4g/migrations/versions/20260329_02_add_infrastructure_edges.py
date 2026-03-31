"""Add infrastructure_edges table for threat-intelligence graph.

Stores entity-to-entity relationships (shared_ip, shared_registrar,
shared_hosting, etc.) discovered by SSI scans and ML pipelines.

Revision ID: 20260329_02
Revises: 20260329_01
Create Date: 2026-03-29

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "20260329_02"
down_revision: str | None = "20260329_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the infrastructure_edges table and indexes."""
    conn = op.get_bind()
    insp = inspect(conn)

    if "infrastructure_edges" not in insp.get_table_names():
        op.create_table(
            "infrastructure_edges",
            sa.Column("edge_id", sa.Text(), primary_key=True),
            sa.Column("source_entity_type", sa.Text(), nullable=False),
            sa.Column("source_canonical_value", sa.Text(), nullable=False),
            sa.Column("target_entity_type", sa.Text(), nullable=False),
            sa.Column("target_canonical_value", sa.Text(), nullable=False),
            sa.Column("edge_type", sa.Text(), nullable=False),
            sa.Column(
                "confidence",
                sa.Numeric(precision=5, scale=4),
                nullable=False,
                server_default="1.0",
            ),
            sa.Column("evidence", sa.JSON(), nullable=True),
            sa.Column(
                "discovered_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
        op.create_index(
            "idx_infra_edges_source",
            "infrastructure_edges",
            ["source_entity_type", "source_canonical_value"],
        )
        op.create_index(
            "idx_infra_edges_target",
            "infrastructure_edges",
            ["target_entity_type", "target_canonical_value"],
        )


def downgrade() -> None:
    """Drop the infrastructure_edges table."""
    conn = op.get_bind()
    insp = inspect(conn)
    if "infrastructure_edges" in insp.get_table_names():
        op.drop_index("idx_infra_edges_target", table_name="infrastructure_edges")
        op.drop_index("idx_infra_edges_source", table_name="infrastructure_edges")
        op.drop_table("infrastructure_edges")
