"""phishdestroy_sprint3_leaks_pivots

Revision ID: 8e2eaf1a25e9
Revises: 20260427_01
Create Date: 2026-04-30

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "8e2eaf1a25e9"
down_revision: str | None = "20260427_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Column type helpers
UUID_TYPE = sa.String(length=64)
TIMESTAMP = sa.DateTime(timezone=True)
JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)

    if not inspector.has_table("leak_records"):
        op.create_table(
            "leak_records",
            sa.Column("leak_id", UUID_TYPE, primary_key=True),
            sa.Column(
                "actor_id",
                UUID_TYPE,
                sa.ForeignKey("threat_actors.actor_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("breach_name", sa.Text(), nullable=False),
            sa.Column("email", sa.Text(), nullable=True),
            sa.Column("password_cleartext", sa.Text(), nullable=True),
            sa.Column("password_hash", sa.Text(), nullable=True),
            sa.Column("ip_address", sa.Text(), nullable=True),
            sa.Column("leak_date", TIMESTAMP, nullable=True),
            sa.Column("metadata_json", JSON_TYPE, nullable=True),
            sa.Column("source_provenance", JSON_TYPE, nullable=True),
            sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("idx_leak_records_actor_id", "leak_records", ["actor_id"])
        op.create_index("idx_leak_records_breach", "leak_records", ["breach_name"])

    if not inspector.has_table("registrant_pivots"):
        op.create_table(
            "registrant_pivots",
            sa.Column("pivot_id", UUID_TYPE, primary_key=True),
            sa.Column("pivot_type", sa.Text(), nullable=False),
            sa.Column("pivot_value", sa.Text(), nullable=False),
            sa.Column(
                "actor_id",
                UUID_TYPE,
                sa.ForeignKey("threat_actors.actor_id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("first_seen_at", TIMESTAMP, nullable=True),
            sa.Column("last_seen_at", TIMESTAMP, nullable=True),
            sa.Column("metadata_json", JSON_TYPE, nullable=True),
            sa.Column("source_provenance", JSON_TYPE, nullable=True),
            sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("pivot_type", "pivot_value", name="uq_registrant_pivots_type_value"),
        )
        op.create_index("idx_registrant_pivots_actor_id", "registrant_pivots", ["actor_id"])


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)

    if inspector.has_table("registrant_pivots"):
        op.drop_table("registrant_pivots")
    if inspector.has_table("leak_records"):
        op.drop_table("leak_records")
