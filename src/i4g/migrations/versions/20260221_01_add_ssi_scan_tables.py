"""Add SSI site scan, wallet, agent session, and PII exposure tables.

Phase 3 (Data Schema & Storage Integration) of the SSI+AWH consolidation
introduces four new tables that capture investigation scan metadata,
harvested cryptocurrency wallets, per-action agent audit trails, and
PII exposure data collected by scam sites.

Revision ID: 20260221_01
Revises: 20260213_01
Create Date: 2026-02-21 12:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "20260221_01"
down_revision: str | None = "20260213_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    existing_tables = insp.get_table_names()

    # --- site_scans ---
    if "site_scans" not in existing_tables:
        op.create_table(
            "site_scans",
            sa.Column("scan_id", sa.String(length=64), primary_key=True),
            sa.Column(
                "case_id",
                sa.Text(),
                sa.ForeignKey("cases.case_id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("url", sa.Text(), nullable=False),
            sa.Column("domain", sa.Text(), nullable=True),
            sa.Column("scan_type", sa.Text(), nullable=False, server_default="passive"),
            sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
            sa.Column("passive_result", sa.JSON(), nullable=True),
            sa.Column("active_result", sa.JSON(), nullable=True),
            sa.Column("classification_result", sa.JSON(), nullable=True),
            sa.Column("risk_score", sa.Numeric(5, 1), nullable=True),
            sa.Column("taxonomy_version", sa.Text(), nullable=True),
            sa.Column("wallet_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total_cost_usd", sa.Numeric(10, 6), nullable=True),
            sa.Column("llm_input_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("llm_output_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("duration_seconds", sa.Numeric(10, 2), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("evidence_path", sa.Text(), nullable=True),
            sa.Column("evidence_zip_sha256", sa.Text(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
        op.create_index("idx_site_scans_case_id", "site_scans", ["case_id"])
        op.create_index("idx_site_scans_domain", "site_scans", ["domain"])
        op.create_index("idx_site_scans_status", "site_scans", ["status"])
        op.create_index("idx_site_scans_created_at", "site_scans", ["created_at"])
        op.create_index("idx_site_scans_risk_score", "site_scans", ["risk_score"])

    # --- harvested_wallets ---
    if "harvested_wallets" not in existing_tables:
        op.create_table(
            "harvested_wallets",
            sa.Column("wallet_id", sa.String(length=64), primary_key=True),
            sa.Column(
                "scan_id",
                sa.String(length=64),
                sa.ForeignKey("site_scans.scan_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "case_id",
                sa.Text(),
                sa.ForeignKey("cases.case_id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("token_label", sa.Text(), nullable=True),
            sa.Column("token_symbol", sa.Text(), nullable=False),
            sa.Column("network_label", sa.Text(), nullable=True),
            sa.Column("network_short", sa.Text(), nullable=False),
            sa.Column("wallet_address", sa.Text(), nullable=False),
            sa.Column("source", sa.Text(), nullable=False, server_default="js"),
            sa.Column("confidence", sa.Numeric(3, 2), nullable=False, server_default="0"),
            sa.Column("site_url", sa.Text(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=True),
            sa.Column("harvested_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.UniqueConstraint(
                "scan_id",
                "token_symbol",
                "network_short",
                "wallet_address",
                name="uq_wallets_scan_token_addr",
            ),
        )
        op.create_index("idx_wallets_scan_id", "harvested_wallets", ["scan_id"])
        op.create_index("idx_wallets_case_id", "harvested_wallets", ["case_id"])
        op.create_index("idx_wallets_address", "harvested_wallets", ["wallet_address"])
        op.create_index("idx_wallets_token_symbol", "harvested_wallets", ["token_symbol"])

    # --- agent_sessions ---
    if "agent_sessions" not in existing_tables:
        op.create_table(
            "agent_sessions",
            sa.Column("session_id", sa.String(length=64), primary_key=True),
            sa.Column(
                "scan_id",
                sa.String(length=64),
                sa.ForeignKey("site_scans.scan_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("state", sa.Text(), nullable=False),
            sa.Column("action_type", sa.Text(), nullable=True),
            sa.Column("action_detail", sa.JSON(), nullable=True),
            sa.Column("screenshot_path", sa.Text(), nullable=True),
            sa.Column("page_url", sa.Text(), nullable=True),
            sa.Column("dom_confidence", sa.Numeric(5, 2), nullable=True),
            sa.Column("llm_model", sa.Text(), nullable=True),
            sa.Column("llm_input_tokens", sa.Integer(), nullable=True),
            sa.Column("llm_output_tokens", sa.Integer(), nullable=True),
            sa.Column("cost_usd", sa.Numeric(10, 6), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("metadata", sa.JSON(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
        op.create_index("idx_agent_sessions_scan_id", "agent_sessions", ["scan_id", "sequence"])
        op.create_index("idx_agent_sessions_state", "agent_sessions", ["state"])

    # --- pii_exposures ---
    if "pii_exposures" not in existing_tables:
        op.create_table(
            "pii_exposures",
            sa.Column("exposure_id", sa.String(length=64), primary_key=True),
            sa.Column(
                "scan_id",
                sa.String(length=64),
                sa.ForeignKey("site_scans.scan_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "case_id",
                sa.Text(),
                sa.ForeignKey("cases.case_id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("field_type", sa.Text(), nullable=False),
            sa.Column("field_label", sa.Text(), nullable=True),
            sa.Column("form_action", sa.Text(), nullable=True),
            sa.Column("page_url", sa.Text(), nullable=True),
            sa.Column("is_required", sa.Boolean(), nullable=True),
            sa.Column("was_submitted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("metadata", sa.JSON(), nullable=True),
            sa.Column("detected_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
        op.create_index("idx_pii_exposures_scan_id", "pii_exposures", ["scan_id"])
        op.create_index("idx_pii_exposures_case_id", "pii_exposures", ["case_id"])
        op.create_index("idx_pii_exposures_field_type", "pii_exposures", ["field_type"])


def downgrade() -> None:
    op.drop_index("idx_pii_exposures_field_type", table_name="pii_exposures")
    op.drop_index("idx_pii_exposures_case_id", table_name="pii_exposures")
    op.drop_index("idx_pii_exposures_scan_id", table_name="pii_exposures")
    op.drop_table("pii_exposures")

    op.drop_index("idx_agent_sessions_state", table_name="agent_sessions")
    op.drop_index("idx_agent_sessions_scan_id", table_name="agent_sessions")
    op.drop_table("agent_sessions")

    op.drop_index("idx_wallets_token_symbol", table_name="harvested_wallets")
    op.drop_index("idx_wallets_address", table_name="harvested_wallets")
    op.drop_index("idx_wallets_case_id", table_name="harvested_wallets")
    op.drop_index("idx_wallets_scan_id", table_name="harvested_wallets")
    op.drop_table("harvested_wallets")

    op.drop_index("idx_site_scans_risk_score", table_name="site_scans")
    op.drop_index("idx_site_scans_created_at", table_name="site_scans")
    op.drop_index("idx_site_scans_status", table_name="site_scans")
    op.drop_index("idx_site_scans_domain", table_name="site_scans")
    op.drop_index("idx_site_scans_case_id", table_name="site_scans")
    op.drop_table("site_scans")
