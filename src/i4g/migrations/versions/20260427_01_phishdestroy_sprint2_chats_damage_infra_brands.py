"""PhishDestroy Sprint 2 Phase A: chat_sessions, financial_damage_claims,
infrastructure_profiles, brand_impersonations tables.

Revision ID: 20260427_01
Revises: 20260425_01
Create Date: 2026-04-27

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "20260427_01"
down_revision: str | None = "20260425_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Column type helpers (must match sql.py definitions)
UUID_TYPE = sa.String(length=64)
CASE_ID_TYPE = sa.Text()  # cases.case_id is Text, not String(64)
TIMESTAMP = sa.DateTime(timezone=True)
JSON_TYPE = sa.JSON()


def _index_exists(inspector: sa.Inspector, table: str, index_name: str) -> bool:
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    # 1. chat_sessions
    # NOTE: chat_ref and evidence_blob_sha256 are PII (transcripts); gate access at API per Sprint 3 RBAC.
    if not inspector.has_table("chat_sessions"):
        op.create_table(
            "chat_sessions",
            sa.Column("session_id", UUID_TYPE, primary_key=True),
            sa.Column("case_id", CASE_ID_TYPE, nullable=True),
            sa.Column("campaign_id", UUID_TYPE, nullable=True),
            sa.Column("actor_id", UUID_TYPE, nullable=True),
            sa.Column("chat_ref", sa.Text(), nullable=False),
            sa.Column("message_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("language", sa.Text(), nullable=True),
            sa.Column("deposit_demand", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("victim_confirmed_send", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("started_at", TIMESTAMP, nullable=True),
            sa.Column("last_message_at", TIMESTAMP, nullable=True),
            sa.Column("evidence_blob_sha256", sa.Text(), nullable=True),  # populated in Phase C
            sa.Column("metadata_json", JSON_TYPE, nullable=True),
            sa.Column("source_provenance", JSON_TYPE, nullable=True),
            sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        with op.batch_alter_table("chat_sessions") as batch_op:
            batch_op.create_foreign_key(
                "fk_chat_sessions_case_id",
                "cases",
                ["case_id"],
                ["case_id"],
                ondelete="SET NULL",
            )
            batch_op.create_foreign_key(
                "fk_chat_sessions_campaign_id",
                "threat_campaigns",
                ["campaign_id"],
                ["campaign_id"],
                ondelete="SET NULL",
            )
            batch_op.create_foreign_key(
                "fk_chat_sessions_actor_id",
                "threat_actors",
                ["actor_id"],
                ["actor_id"],
                ondelete="SET NULL",
            )
    if not _index_exists(inspector, "chat_sessions", "idx_chat_sessions_campaign_id"):
        op.create_index("idx_chat_sessions_campaign_id", "chat_sessions", ["campaign_id"])
    if not _index_exists(inspector, "chat_sessions", "idx_chat_sessions_actor_id"):
        op.create_index("idx_chat_sessions_actor_id", "chat_sessions", ["actor_id"])
    if not _index_exists(inspector, "chat_sessions", "idx_chat_sessions_case_id"):
        op.create_index("idx_chat_sessions_case_id", "chat_sessions", ["case_id"])

    # 2. financial_damage_claims
    if not inspector.has_table("financial_damage_claims"):
        op.create_table(
            "financial_damage_claims",
            sa.Column("claim_id", UUID_TYPE, primary_key=True),
            sa.Column("case_id", CASE_ID_TYPE, nullable=True),
            sa.Column("campaign_id", UUID_TYPE, nullable=True),
            sa.Column("session_id", UUID_TYPE, nullable=True),
            sa.Column("currency", sa.Text(), nullable=False),
            sa.Column("chain", sa.Text(), nullable=True),
            sa.Column("amount_claimed", sa.Numeric(36, 18), nullable=False),
            sa.Column("amount_confirmed", sa.Numeric(36, 18), nullable=True),
            sa.Column("tx_hash", sa.Text(), nullable=True),
            sa.Column("wallet_address", sa.Text(), nullable=True),
            sa.Column("verification_status", sa.Text(), nullable=False, server_default=sa.text("'unverified'")),
            sa.Column("metadata_json", JSON_TYPE, nullable=True),
            sa.Column("source_provenance", JSON_TYPE, nullable=True),
            sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        with op.batch_alter_table("financial_damage_claims") as batch_op:
            batch_op.create_foreign_key(
                "fk_financial_damage_claims_case_id",
                "cases",
                ["case_id"],
                ["case_id"],
                ondelete="SET NULL",
            )
            batch_op.create_foreign_key(
                "fk_financial_damage_claims_campaign_id",
                "threat_campaigns",
                ["campaign_id"],
                ["campaign_id"],
                ondelete="SET NULL",
            )
            batch_op.create_foreign_key(
                "fk_financial_damage_claims_session_id",
                "chat_sessions",
                ["session_id"],
                ["session_id"],
                ondelete="SET NULL",
            )
    if not _index_exists(inspector, "financial_damage_claims", "idx_fdc_campaign_currency"):
        op.create_index("idx_fdc_campaign_currency", "financial_damage_claims", ["campaign_id", "currency"])
    if not _index_exists(inspector, "financial_damage_claims", "idx_fdc_session_id"):
        op.create_index("idx_fdc_session_id", "financial_damage_claims", ["session_id"])
    if not _index_exists(inspector, "financial_damage_claims", "idx_fdc_case_id"):
        op.create_index("idx_fdc_case_id", "financial_damage_claims", ["case_id"])

    # 3. infrastructure_profiles
    if not inspector.has_table("infrastructure_profiles"):
        op.create_table(
            "infrastructure_profiles",
            sa.Column("profile_id", UUID_TYPE, primary_key=True),
            sa.Column("campaign_id", UUID_TYPE, nullable=False),
            sa.Column("primary_domain", sa.Text(), nullable=False),
            sa.Column("subdomain_roles", JSON_TYPE, nullable=True),
            sa.Column("tech_stack", JSON_TYPE, nullable=True),
            sa.Column("source_maps_exposed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("auth_model", sa.Text(), nullable=True),
            sa.Column("cors_config", sa.Text(), nullable=True),
            sa.Column("metadata_json", JSON_TYPE, nullable=True),
            sa.Column("source_provenance", JSON_TYPE, nullable=True),
            sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("campaign_id", "primary_domain", name="uq_infrastructure_profiles_campaign_domain"),
        )
        with op.batch_alter_table("infrastructure_profiles") as batch_op:
            batch_op.create_foreign_key(
                "fk_infrastructure_profiles_campaign_id",
                "threat_campaigns",
                ["campaign_id"],
                ["campaign_id"],
                ondelete="CASCADE",
            )

    # 4. brand_impersonations
    if not inspector.has_table("brand_impersonations"):
        op.create_table(
            "brand_impersonations",
            sa.Column("impersonation_id", UUID_TYPE, primary_key=True),
            sa.Column("indicator_id", UUID_TYPE, nullable=False),
            sa.Column("brand", sa.Text(), nullable=False),
            sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
            sa.Column("detected_by", sa.Text(), nullable=True),
            sa.Column("metadata_json", JSON_TYPE, nullable=True),
            sa.Column("source_provenance", JSON_TYPE, nullable=True),
            sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("indicator_id", "brand", name="uq_brand_impersonations_indicator_brand"),
        )
        with op.batch_alter_table("brand_impersonations") as batch_op:
            batch_op.create_foreign_key(
                "fk_brand_impersonations_indicator_id",
                "indicators",
                ["indicator_id"],
                ["indicator_id"],
                ondelete="CASCADE",
            )
    if not _index_exists(inspector, "brand_impersonations", "idx_brand_impersonations_brand"):
        op.create_index("idx_brand_impersonations_brand", "brand_impersonations", ["brand"])
    if not _index_exists(inspector, "brand_impersonations", "idx_brand_impersonations_indicator_id"):
        op.create_index("idx_brand_impersonations_indicator_id", "brand_impersonations", ["indicator_id"])


def downgrade() -> None:
    # Drop in strict reverse creation order (most-dependent child tables first).

    # 4. brand_impersonations
    op.drop_index("idx_brand_impersonations_indicator_id", table_name="brand_impersonations")
    op.drop_index("idx_brand_impersonations_brand", table_name="brand_impersonations")
    with op.batch_alter_table("brand_impersonations") as batch_op:
        batch_op.drop_constraint("fk_brand_impersonations_indicator_id", type_="foreignkey")
    op.drop_table("brand_impersonations")

    # 3. infrastructure_profiles
    with op.batch_alter_table("infrastructure_profiles") as batch_op:
        batch_op.drop_constraint("fk_infrastructure_profiles_campaign_id", type_="foreignkey")
    op.drop_table("infrastructure_profiles")

    # 2. financial_damage_claims (FK to chat_sessions — must drop before chat_sessions)
    op.drop_index("idx_fdc_case_id", table_name="financial_damage_claims")
    op.drop_index("idx_fdc_session_id", table_name="financial_damage_claims")
    op.drop_index("idx_fdc_campaign_currency", table_name="financial_damage_claims")
    with op.batch_alter_table("financial_damage_claims") as batch_op:
        batch_op.drop_constraint("fk_financial_damage_claims_session_id", type_="foreignkey")
        batch_op.drop_constraint("fk_financial_damage_claims_campaign_id", type_="foreignkey")
        batch_op.drop_constraint("fk_financial_damage_claims_case_id", type_="foreignkey")
    op.drop_table("financial_damage_claims")

    # 1. chat_sessions
    op.drop_index("idx_chat_sessions_case_id", table_name="chat_sessions")
    op.drop_index("idx_chat_sessions_actor_id", table_name="chat_sessions")
    op.drop_index("idx_chat_sessions_campaign_id", table_name="chat_sessions")
    with op.batch_alter_table("chat_sessions") as batch_op:
        batch_op.drop_constraint("fk_chat_sessions_actor_id", type_="foreignkey")
        batch_op.drop_constraint("fk_chat_sessions_campaign_id", type_="foreignkey")
        batch_op.drop_constraint("fk_chat_sessions_case_id", type_="foreignkey")
    op.drop_table("chat_sessions")
