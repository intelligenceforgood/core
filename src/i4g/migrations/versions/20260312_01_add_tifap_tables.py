"""Add TIFAP tables: threat_campaigns, threat_campaign_cases,
intake_indicator_links, entity_stats, indicator_stats, campaign_stats,
platform_kpis; add loss_currency and victim_country columns to
intake_records; add ingestion_batch_id column to cases.

Sprint 1 of the Threat Intelligence & Fraud Analytics Platform (TIFAP)
implementation plan. Creates the pre-computed aggregation layer, threat
campaign model, and schema prerequisites.

Revision ID: 20260312_01
Revises: 20260306_01
Create Date: 2026-03-12

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "20260312_01"
down_revision: str | None = "20260306_01"
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
    """Create TIFAP tables and add new columns."""
    conn = op.get_bind()
    insp = inspect(conn)

    # --- S1-01: threat_campaigns ---
    if not _table_exists(insp, "threat_campaigns"):
        op.create_table(
            "threat_campaigns",
            sa.Column("campaign_id", sa.String(length=64), primary_key=True),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("origin", sa.Text(), nullable=False, server_default="manual"),
            sa.Column("status", sa.Text(), nullable=False, server_default="emerging"),
            sa.Column("risk_score", sa.Numeric(5, 1), nullable=False, server_default="0"),
            sa.Column("taxonomy_rollup", sa.JSON(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=True),
            sa.Column("created_by", sa.Text(), nullable=False, server_default="system"),
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
        op.create_index("idx_threat_campaigns_status", "threat_campaigns", ["status"])
        op.create_index("idx_threat_campaigns_risk_score", "threat_campaigns", ["risk_score"])

    # --- S1-02: threat_campaign_cases ---
    if not _table_exists(insp, "threat_campaign_cases"):
        op.create_table(
            "threat_campaign_cases",
            sa.Column(
                "campaign_id",
                sa.String(length=64),
                sa.ForeignKey("threat_campaigns.campaign_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "case_id",
                sa.Text(),
                sa.ForeignKey("cases.case_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "linked_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column("linked_by", sa.Text(), nullable=False, server_default="manual"),
            sa.Column("link_reason", sa.Text(), nullable=True),
            sa.UniqueConstraint("campaign_id", "case_id", name="uq_threat_campaign_cases"),
        )
        op.create_index("idx_tcc_campaign_id", "threat_campaign_cases", ["campaign_id"])
        op.create_index("idx_tcc_case_id", "threat_campaign_cases", ["case_id"])

    # --- S1-03: intake_indicator_links ---
    if not _table_exists(insp, "intake_indicator_links"):
        op.create_table(
            "intake_indicator_links",
            sa.Column(
                "intake_id",
                sa.Text(),
                sa.ForeignKey("intake_records.intake_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "indicator_id",
                sa.String(length=64),
                sa.ForeignKey("indicators.indicator_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("confidence", sa.Numeric(5, 4), nullable=False, server_default="0"),
            sa.Column("linked_by", sa.Text(), nullable=False, server_default="system"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.PrimaryKeyConstraint("intake_id", "indicator_id", name="pk_intake_indicator_links"),
        )
        op.create_index("idx_iil_indicator_id", "intake_indicator_links", ["indicator_id"])

    # --- S1-04: loss_currency on intake_records ---
    if not _column_exists(insp, "intake_records", "loss_currency"):
        op.add_column(
            "intake_records",
            sa.Column("loss_currency", sa.Text(), nullable=True, server_default="USD"),
        )

    # --- S1-05: ingestion_batch_id on cases ---
    if not _column_exists(insp, "cases", "ingestion_batch_id"):
        op.add_column(
            "cases",
            sa.Column("ingestion_batch_id", sa.String(length=64), nullable=True),
        )
        op.create_index("idx_cases_ingestion_batch_id", "cases", ["ingestion_batch_id"])

    # --- S1-06: victim_country on intake_records ---
    if not _column_exists(insp, "intake_records", "victim_country"):
        op.add_column(
            "intake_records",
            sa.Column("victim_country", sa.Text(), nullable=True),
        )

    # --- S1-07: entity_stats ---
    if not _table_exists(insp, "entity_stats"):
        op.create_table(
            "entity_stats",
            sa.Column("entity_type", sa.Text(), nullable=False),
            sa.Column("canonical_value", sa.Text(), nullable=False),
            sa.Column("case_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("victim_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("loss_sum", sa.Numeric(14, 2), nullable=False, server_default="0"),
            sa.Column("loss_currency", sa.Text(), nullable=False, server_default="USD"),
            sa.Column("max_risk_score", sa.Numeric(5, 1), nullable=False, server_default="0"),
            sa.Column("avg_risk_score", sa.Numeric(5, 1), nullable=False, server_default="0"),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.Text(), nullable=False, server_default="active"),
            sa.Column("campaign_ids", sa.JSON(), nullable=True),
            sa.Column("top_classifications", sa.JSON(), nullable=True),
            sa.Column("ecx_submitted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("ecx_hit", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("purge_status", sa.Text(), nullable=True),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.PrimaryKeyConstraint("entity_type", "canonical_value", name="pk_entity_stats"),
        )
        op.create_index("idx_entity_stats_status", "entity_stats", ["status"])
        op.create_index("idx_entity_stats_case_count", "entity_stats", ["case_count"])
        op.create_index("idx_entity_stats_loss_sum", "entity_stats", ["loss_sum"])

    # --- S1-08: indicator_stats ---
    if not _table_exists(insp, "indicator_stats"):
        op.create_table(
            "indicator_stats",
            sa.Column("indicator_id", sa.String(length=64), primary_key=True),
            sa.Column("category", sa.Text(), nullable=False),
            sa.Column("item", sa.Text(), nullable=True),
            sa.Column("type", sa.Text(), nullable=False),
            sa.Column("number", sa.Text(), nullable=False),
            sa.Column("case_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("loss_sum", sa.Numeric(14, 2), nullable=False, server_default="0"),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("max_risk_score", sa.Numeric(5, 1), nullable=False, server_default="0"),
            sa.Column("ecx_status", sa.Text(), nullable=False, server_default="not_submitted"),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
        op.create_index("idx_indicator_stats_category", "indicator_stats", ["category"])
        op.create_index("idx_indicator_stats_case_count", "indicator_stats", ["case_count"])

    # --- S1-09: campaign_stats ---
    if not _table_exists(insp, "campaign_stats"):
        op.create_table(
            "campaign_stats",
            sa.Column(
                "campaign_id",
                sa.String(length=64),
                sa.ForeignKey("threat_campaigns.campaign_id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("case_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("indicator_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("entity_types", sa.JSON(), nullable=True),
            sa.Column("loss_sum", sa.Numeric(14, 2), nullable=False, server_default="0"),
            sa.Column("victim_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("risk_score", sa.Numeric(5, 1), nullable=False, server_default="0"),
            sa.Column("taxonomy_rollup", sa.JSON(), nullable=True),
            sa.Column("first_case_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_case_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.Text(), nullable=False, server_default="emerging"),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )

    # --- S1-10: platform_kpis ---
    if not _table_exists(insp, "platform_kpis"):
        op.create_table(
            "platform_kpis",
            sa.Column("period_type", sa.Text(), nullable=False),
            sa.Column("period_start", sa.Date(), nullable=False),
            sa.Column("total_cases", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("proactive_cases", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("reactive_cases", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total_loss", sa.Numeric(14, 2), nullable=False, server_default="0"),
            sa.Column("new_indicators", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("new_entities", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("site_scans", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("ecx_submissions", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cases_actioned", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("median_action_hours", sa.Numeric(10, 2), nullable=True),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.PrimaryKeyConstraint("period_type", "period_start", name="pk_platform_kpis"),
        )


def downgrade() -> None:
    """Drop TIFAP tables and remove added columns."""
    conn = op.get_bind()
    insp = inspect(conn)

    for table_name in (
        "platform_kpis",
        "campaign_stats",
        "indicator_stats",
        "entity_stats",
        "intake_indicator_links",
        "threat_campaign_cases",
        "threat_campaigns",
    ):
        if _table_exists(insp, table_name):
            op.drop_table(table_name)

    if _column_exists(insp, "cases", "ingestion_batch_id"):
        op.drop_column("cases", "ingestion_batch_id")

    if _column_exists(insp, "intake_records", "loss_currency"):
        op.drop_column("intake_records", "loss_currency")

    if _column_exists(insp, "intake_records", "victim_country"):
        op.drop_column("intake_records", "victim_country")
