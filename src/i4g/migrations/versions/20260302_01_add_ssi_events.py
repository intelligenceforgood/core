"""Add ssi_events table for cloud live-monitoring via SSE.

Phase 3B of the SSI Case Enrichment & Live Monitor plan persists
investigation events to the core database so they can be:

  * Streamed in real-time to the UI via Server-Sent Events (SSE)
    after being published to a Redis pub/sub channel.
  * Replayed from the database on the ``/ssi/investigations/{id}``
    detail page even when the investigation is no longer running.

Revision ID: 20260302_01
Revises: 20260225_01
Create Date: 2026-03-02

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

# revision identifiers, used by Alembic.
revision: str = "20260302_01"
down_revision: Union[str, None] = "20260225_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the ssi_events table."""
    conn = op.get_bind()
    insp = inspect(conn)
    existing_tables = insp.get_table_names()

    if "ssi_events" not in existing_tables:
        op.create_table(
            "ssi_events",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column(
                "scan_id",
                sa.String(length=64),
                sa.ForeignKey("site_scans.scan_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("event_type", sa.Text(), nullable=False),
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
            # Carries all event data; screenshots stored as inline base64 here.
            sa.Column("data_json", sa.JSON(), nullable=True),
            # Reserved for future GCS-backed screenshots (nullable).
            sa.Column("screenshot_url", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=text("CURRENT_TIMESTAMP"),
            ),
        )
        op.create_index("idx_ssi_events_scan_id", "ssi_events", ["scan_id"])
        op.create_index(
            "idx_ssi_events_timestamp",
            "ssi_events",
            ["scan_id", "timestamp"],
        )
        op.create_index("idx_ssi_events_event_type", "ssi_events", ["event_type"])


def downgrade() -> None:
    """Drop the ssi_events table."""
    conn = op.get_bind()
    insp = inspect(conn)
    if "ssi_events" in insp.get_table_names():
        op.drop_index("idx_ssi_events_event_type", table_name="ssi_events")
        op.drop_index("idx_ssi_events_timestamp", table_name="ssi_events")
        op.drop_index("idx_ssi_events_scan_id", table_name="ssi_events")
        op.drop_table("ssi_events")
