"""SQLAlchemy metadata and engine helpers for the dual-write ingestion tables."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from i4g.settings import Settings, get_settings

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
TIMESTAMP = sa.DateTime(timezone=True)
UUID_TYPE = sa.String(length=64)

METADATA = sa.MetaData()
VAULT_METADATA = sa.MetaData()

accounts = sa.Table(
    "accounts",
    METADATA,
    sa.Column("email", sa.Text(), primary_key=True),
    sa.Column("role", sa.Text(), nullable=False, server_default="analyst"),
    sa.Column("display_name", sa.Text(), nullable=True),
    sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.Column("updated_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
)
sa.Index("idx_accounts_role", accounts.c.role)

account_actions = sa.Table(
    "account_actions",
    METADATA,
    sa.Column("action_id", sa.Text(), primary_key=True),
    sa.Column("target_email", sa.Text(), nullable=False),
    sa.Column("actor", sa.Text(), nullable=True),
    sa.Column("action", sa.Text(), nullable=False),
    sa.Column("payload", JSON_TYPE, nullable=True),
    sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
)
sa.Index("idx_account_actions_target", account_actions.c.target_email)
sa.Index("idx_account_actions_created_at", account_actions.c.created_at)

ingestion_runs = sa.Table(
    "ingestion_runs",
    METADATA,
    sa.Column("run_id", UUID_TYPE, primary_key=True),
    sa.Column("dataset", sa.Text(), nullable=False),
    sa.Column("source_bundle", sa.Text(), nullable=True),
    sa.Column("started_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.Column("completed_at", TIMESTAMP, nullable=True),
    sa.Column("status", sa.Text(), nullable=False),
    sa.Column("case_count", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("entity_count", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("indicator_count", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("vertex_writes", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("sql_writes", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("vector_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    sa.Column("metadata", JSON_TYPE, nullable=True),
    sa.Column("last_error", sa.Text(), nullable=True),
    sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.Column("updated_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
)
sa.Index("idx_ingestion_runs_started_at", ingestion_runs.c.started_at)
sa.Index("idx_ingestion_runs_status", ingestion_runs.c.status)

campaigns = sa.Table(
    "campaigns",
    METADATA,
    sa.Column("campaign_id", UUID_TYPE, primary_key=True),
    sa.Column("name", sa.Text(), nullable=False),
    sa.Column("description", sa.Text(), nullable=True),
    sa.Column("taxonomy_labels", JSON_TYPE, nullable=True),
    sa.Column("taxonomy_rollup", JSON_TYPE, server_default=sa.text("'[]'")),
    sa.Column("status", sa.Text(), nullable=False, server_default="active"),
    sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.Column("updated_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
)

pii_tokens = sa.Table(
    "pii_tokens",
    VAULT_METADATA,
    sa.Column("token", sa.String(length=20), primary_key=True),
    sa.Column("prefix", sa.String(length=3), nullable=False),
    sa.Column("digest", sa.String(length=64), nullable=False),
    sa.Column("normalized_value", sa.Text(), nullable=False),
    sa.Column("canonical_value", sa.Text(), nullable=True),
    sa.Column("encrypted_value", sa.LargeBinary(), nullable=True),
    sa.Column("pepper_version", sa.String(length=10), nullable=False),
    sa.Column("detector", sa.String(length=50), nullable=True),
    sa.Column("case_id", sa.String(length=64), nullable=True),
    sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
)
sa.Index("idx_pii_tokens_digest", pii_tokens.c.digest)
sa.Index("idx_pii_tokens_prefix", pii_tokens.c.prefix)

audit_log = sa.Table(
    "audit_log",
    VAULT_METADATA,
    sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
    sa.Column("timestamp", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.Column("actor", sa.Text(), nullable=False),
    sa.Column("action", sa.Text(), nullable=False),
    sa.Column("token", sa.Text(), nullable=True),
    sa.Column("prefix", sa.Text(), nullable=True),
    sa.Column("outcome", sa.Text(), nullable=False),
    sa.Column("reason", sa.Text(), nullable=True),
    sa.Column("case_id", sa.Text(), nullable=True),
)
sa.Index("idx_audit_log_token", audit_log.c.token)
sa.Index("idx_audit_log_actor", audit_log.c.actor)

cases = sa.Table(
    "cases",
    METADATA,
    sa.Column("case_id", sa.Text(), primary_key=True),
    sa.Column(
        "ingestion_run_id", UUID_TYPE, sa.ForeignKey("ingestion_runs.run_id", ondelete="SET NULL"), nullable=True
    ),
    sa.Column("campaign_id", UUID_TYPE, sa.ForeignKey("campaigns.campaign_id", ondelete="SET NULL"), nullable=True),
    sa.Column("ingestion_batch_id", UUID_TYPE, nullable=True),
    sa.Column("dataset", sa.Text(), nullable=False),
    sa.Column("source_type", sa.Text(), nullable=False),
    sa.Column("classification", sa.Text(), nullable=True),  # Changed from JSON_TYPE to Text for label
    sa.Column("classification_status", sa.Text(), nullable=False, server_default="pending"),
    sa.Column("classification_result", JSON_TYPE, nullable=True),
    sa.Column("tags", JSON_TYPE, nullable=True),
    sa.Column("confidence", sa.Numeric(5, 4), nullable=False, server_default="0"),
    sa.Column("risk_score", sa.Numeric(5, 1), nullable=False, server_default="0"),
    sa.Column("taxonomy_version", sa.Text(), nullable=True),
    sa.Column("detected_at", TIMESTAMP, nullable=True),
    sa.Column("reported_at", TIMESTAMP, nullable=True),
    sa.Column("raw_text_sha256", sa.Text(), nullable=False),
    sa.Column("status", sa.Text(), nullable=False, server_default="open"),
    sa.Column("metadata", JSON_TYPE, nullable=True),
    sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    sa.Column("deleted_at", TIMESTAMP, nullable=True),
    sa.Column("resolved_at", TIMESTAMP, nullable=True),
    sa.Column("purged_at", TIMESTAMP, nullable=True),
    sa.Column("lea_referred_at", TIMESTAMP, nullable=True),
    sa.Column("lea_agency", sa.Text(), nullable=True),
    sa.Column("lea_case_number", sa.Text(), nullable=True),
    sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.Column("updated_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.UniqueConstraint("dataset", "raw_text_sha256", name="uq_cases_dataset_rawsha"),
)
sa.Index("idx_cases_dataset_reported_at", cases.c.dataset, cases.c.reported_at)
sa.Index("idx_cases_classification_status", cases.c.classification_status)
sa.Index("idx_cases_classification", cases.c.classification)
sa.Index("idx_cases_tags", cases.c.tags, postgresql_using="gin")  # GIN index for tags array
sa.Index("idx_cases_status", cases.c.status)
sa.Index("idx_cases_risk_score", cases.c.risk_score)
sa.Index("idx_cases_created_at", cases.c.created_at)
sa.Index("idx_cases_created_at_classification", cases.c.created_at, cases.c.classification)

source_documents = sa.Table(
    "source_documents",
    METADATA,
    sa.Column("document_id", UUID_TYPE, primary_key=True),
    sa.Column("case_id", sa.Text(), sa.ForeignKey("cases.case_id", ondelete="CASCADE"), nullable=False),
    sa.Column("title", sa.Text(), nullable=True),
    sa.Column("source_url", sa.Text(), nullable=True),
    sa.Column("mime_type", sa.Text(), nullable=True),
    sa.Column("text", sa.Text(), nullable=True),
    sa.Column("text_sha256", sa.Text(), nullable=True),
    sa.Column("excerpt", sa.Text(), nullable=True),
    sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="1"),
    sa.Column("score", sa.Numeric(6, 3), nullable=True),
    sa.Column("captured_at", TIMESTAMP, nullable=True),
    sa.Column("file_sha256", sa.Text(), nullable=True),
    sa.Column("ingested_at", TIMESTAMP, nullable=True),
    sa.Column("metadata", JSON_TYPE, nullable=True),
    sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.Column("updated_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
)
sa.Index("idx_documents_case", source_documents.c.case_id, source_documents.c.captured_at)

entities = sa.Table(
    "entities",
    METADATA,
    sa.Column("entity_id", UUID_TYPE, primary_key=True),
    sa.Column("case_id", sa.Text(), sa.ForeignKey("cases.case_id", ondelete="CASCADE"), nullable=False),
    sa.Column("entity_type", sa.Text(), nullable=False),
    sa.Column("canonical_value", sa.Text(), nullable=False),
    sa.Column("raw_value", sa.Text(), nullable=True),
    sa.Column("confidence", sa.Numeric(5, 4), nullable=False, server_default="0"),
    sa.Column("first_seen_at", TIMESTAMP, nullable=True),
    sa.Column("last_seen_at", TIMESTAMP, nullable=True),
    sa.Column("metadata", JSON_TYPE, nullable=True),
    sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.Column("updated_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.UniqueConstraint("case_id", "entity_type", "canonical_value", name="uq_entities_case_type_value"),
)
sa.Index("idx_entities_type_value", entities.c.entity_type, entities.c.canonical_value)
sa.Index("idx_entities_case_id", entities.c.case_id)

entity_mentions = sa.Table(
    "entity_mentions",
    METADATA,
    sa.Column("entity_id", UUID_TYPE, sa.ForeignKey("entities.entity_id", ondelete="CASCADE"), nullable=False),
    sa.Column(
        "document_id", UUID_TYPE, sa.ForeignKey("source_documents.document_id", ondelete="CASCADE"), nullable=False
    ),
    sa.Column("span_start", sa.Integer(), nullable=True),
    sa.Column("span_end", sa.Integer(), nullable=True),
    sa.Column("sentence", sa.Text(), nullable=True),
    sa.Column("metadata", JSON_TYPE, nullable=True),
    sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.PrimaryKeyConstraint("entity_id", "document_id", "span_start", name="pk_entity_mentions"),
)
sa.Index("idx_entity_mentions_document", entity_mentions.c.document_id)

indicators = sa.Table(
    "indicators",
    METADATA,
    sa.Column("indicator_id", UUID_TYPE, primary_key=True),
    sa.Column("case_id", sa.Text(), sa.ForeignKey("cases.case_id", ondelete="CASCADE"), nullable=False),
    sa.Column("category", sa.Text(), nullable=False),
    sa.Column("item", sa.Text(), nullable=True),
    sa.Column("type", sa.Text(), nullable=False),
    sa.Column("number", sa.Text(), nullable=False),
    sa.Column("status", sa.Text(), nullable=False, server_default="active"),
    sa.Column("confidence", sa.Numeric(5, 4), nullable=False, server_default="0"),
    sa.Column("first_seen_at", TIMESTAMP, nullable=True),
    sa.Column("last_seen_at", TIMESTAMP, nullable=True),
    sa.Column("dataset", sa.Text(), nullable=False),
    sa.Column("metadata", JSON_TYPE, nullable=True),
    sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.Column("updated_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.UniqueConstraint("dataset", "category", "number", name="uq_indicators_dataset_category_number"),
)
sa.Index("idx_indicators_category_number", indicators.c.category, indicators.c.number)
sa.Index("idx_indicators_case_id", indicators.c.case_id)
sa.Index("idx_indicators_last_seen_at", indicators.c.last_seen_at)

dossier_queue = sa.Table(
    "dossier_queue",
    METADATA,
    sa.Column("plan_id", sa.Text(), primary_key=True),
    sa.Column("status", sa.Text(), nullable=False),
    sa.Column("priority", sa.Text(), nullable=False),
    sa.Column("payload", sa.Text(), nullable=False),
    sa.Column("queued_at", TIMESTAMP, nullable=False),
    sa.Column("updated_at", TIMESTAMP, nullable=False),
    sa.Column("error", sa.Text(), nullable=True),
    sa.Column("warnings", sa.Text(), nullable=True),
)
sa.Index("idx_dossier_queue_status", dossier_queue.c.status)

indicator_sources = sa.Table(
    "indicator_sources",
    METADATA,
    sa.Column("indicator_id", UUID_TYPE, sa.ForeignKey("indicators.indicator_id", ondelete="CASCADE"), nullable=False),
    sa.Column(
        "document_id", UUID_TYPE, sa.ForeignKey("source_documents.document_id", ondelete="CASCADE"), nullable=False
    ),
    sa.Column("entity_id", UUID_TYPE, sa.ForeignKey("entities.entity_id", ondelete="SET NULL"), nullable=True),
    sa.Column("evidence_score", sa.Numeric(5, 4), nullable=True),
    sa.Column("explanation", sa.Text(), nullable=True),
    sa.Column("metadata", JSON_TYPE, nullable=True),
    sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.PrimaryKeyConstraint("indicator_id", "document_id", name="pk_indicator_sources"),
)
sa.Index("idx_indicator_sources_document", indicator_sources.c.document_id)

ingestion_retry_queue = sa.Table(
    "ingestion_retry_queue",
    METADATA,
    sa.Column("retry_id", UUID_TYPE, primary_key=True),
    sa.Column("case_id", sa.Text(), nullable=False),
    sa.Column("backend", sa.Text(), nullable=False),
    sa.Column("payload_json", JSON_TYPE, nullable=False),
    sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("next_attempt_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.Column("updated_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
)
sa.Index("idx_retry_queue_case_backend", ingestion_retry_queue.c.case_id, ingestion_retry_queue.c.backend)


scam_records = sa.Table(
    "scam_records",
    METADATA,
    sa.Column("case_id", sa.Text(), primary_key=True),
    sa.Column("text", sa.Text(), nullable=True),
    sa.Column("entities", JSON_TYPE, nullable=True),
    sa.Column("classification", sa.Text(), nullable=True),
    sa.Column("confidence", sa.Float(), nullable=True),
    sa.Column("classification_result", JSON_TYPE, nullable=True),
    sa.Column("tags", JSON_TYPE, nullable=True),
    sa.Column("created_at", TIMESTAMP, nullable=True),
    sa.Column("embedding", JSON_TYPE, nullable=True),
    sa.Column("metadata", JSON_TYPE, nullable=True),
)

review_queue = sa.Table(
    "review_queue",
    METADATA,
    sa.Column("review_id", sa.Text(), primary_key=True),
    sa.Column("case_id", sa.Text(), nullable=False),
    sa.Column("queued_at", TIMESTAMP, nullable=False),
    sa.Column("priority", sa.Text(), server_default="medium"),
    sa.Column("status", sa.Text(), server_default="new"),
    sa.Column("assigned_to", sa.Text(), nullable=True),
    sa.Column("notes", sa.Text(), nullable=True),
    sa.Column("last_updated", TIMESTAMP, nullable=True),
    sa.Column("classification_result", JSON_TYPE, nullable=True),
    sa.Column("tags", JSON_TYPE, nullable=True),
)
sa.Index("idx_review_queue_status", review_queue.c.status)
sa.Index("idx_review_queue_priority", review_queue.c.priority)
sa.Index("idx_review_queue_case_id", review_queue.c.case_id)
sa.Index("idx_review_queue_queued_at", review_queue.c.queued_at)

review_actions = sa.Table(
    "review_actions",
    METADATA,
    sa.Column("action_id", sa.Text(), primary_key=True),
    sa.Column("review_id", sa.Text(), sa.ForeignKey("review_queue.review_id"), nullable=False),
    sa.Column("actor", sa.Text(), nullable=True),
    sa.Column("action", sa.Text(), nullable=True),
    sa.Column("payload", JSON_TYPE, nullable=True),
    sa.Column("created_at", TIMESTAMP, nullable=True),
)
sa.Index("idx_review_actions_review_id", review_actions.c.review_id)
sa.Index("idx_review_actions_created_at", review_actions.c.created_at)

saved_searches = sa.Table(
    "saved_searches",
    METADATA,
    sa.Column("search_id", sa.Text(), primary_key=True),
    sa.Column("name", sa.Text(), nullable=False),
    sa.Column("owner", sa.Text(), nullable=True),
    sa.Column("params", JSON_TYPE, nullable=True),
    sa.Column("created_at", TIMESTAMP, nullable=True),
    sa.Column("favorite", sa.Boolean(), server_default=sa.text("false")),
    sa.Column("tags", JSON_TYPE, server_default=sa.text("'[]'")),
)


intake_records = sa.Table(
    "intake_records",
    METADATA,
    sa.Column("intake_id", sa.Text(), primary_key=True),
    sa.Column("reporter_name", sa.Text(), nullable=True),
    sa.Column("contact_email", sa.Text(), nullable=True),
    sa.Column("contact_phone", sa.Text(), nullable=True),
    sa.Column("contact_handle", sa.Text(), nullable=True),
    sa.Column("contact_channel", sa.Text(), nullable=True),
    sa.Column("contact_identifier", sa.Text(), nullable=True),
    sa.Column("preferred_contact", sa.Text(), nullable=True),
    sa.Column("incident_date", sa.Text(), nullable=True),
    sa.Column("loss_amount", sa.Float(), nullable=True),
    sa.Column("summary", sa.Text(), nullable=True),
    sa.Column("details", sa.Text(), nullable=True),
    sa.Column("status", sa.Text(), nullable=True),
    sa.Column("submitted_by", sa.Text(), nullable=True),
    sa.Column("source", sa.Text(), nullable=True),
    sa.Column("case_id", sa.Text(), nullable=True),
    sa.Column("review_id", sa.Text(), nullable=True),
    sa.Column("job_id", sa.Text(), nullable=True),
    sa.Column("job_status", sa.Text(), nullable=True),
    sa.Column("job_message", sa.Text(), nullable=True),
    sa.Column("loss_currency", sa.Text(), nullable=True, server_default="USD"),
    sa.Column("victim_country", sa.Text(), nullable=True),
    sa.Column("victim_age_range", sa.Text(), nullable=True),
    sa.Column("metadata", JSON_TYPE, nullable=True),
    sa.Column("created_at", TIMESTAMP, nullable=True),
    sa.Column("updated_at", TIMESTAMP, nullable=True),
)
sa.Index("idx_intake_records_created_at", intake_records.c.created_at)
sa.Index("idx_intake_records_case_id", intake_records.c.case_id)
sa.Index("idx_intake_records_victim_country", intake_records.c.victim_country)

intake_attachments = sa.Table(
    "intake_attachments",
    METADATA,
    sa.Column("attachment_id", sa.Text(), primary_key=True),
    sa.Column("intake_id", sa.Text(), sa.ForeignKey("intake_records.intake_id"), nullable=False),
    sa.Column("file_name", sa.Text(), nullable=True),
    sa.Column("content_type", sa.Text(), nullable=True),
    sa.Column("size_bytes", sa.Integer(), nullable=True),
    sa.Column("checksum_sha256", sa.Text(), nullable=True),
    sa.Column("storage_uri", sa.Text(), nullable=True),
    sa.Column("storage_backend", sa.Text(), nullable=True),
    sa.Column("created_at", TIMESTAMP, nullable=True),
)

intake_jobs = sa.Table(
    "intake_jobs",
    METADATA,
    sa.Column("job_id", sa.Text(), primary_key=True),
    sa.Column("intake_id", sa.Text(), sa.ForeignKey("intake_records.intake_id"), nullable=False),
    sa.Column("status", sa.Text(), nullable=True),
    sa.Column("message", sa.Text(), nullable=True),
    sa.Column("metadata", JSON_TYPE, nullable=True),
    sa.Column("created_at", TIMESTAMP, nullable=True),
    sa.Column("updated_at", TIMESTAMP, nullable=True),
)

# ---------------------------------------------------------------------------
# SSI: Site Scans, Harvested Wallets, Agent Sessions, PII Exposures
# ---------------------------------------------------------------------------

site_scans = sa.Table(
    "site_scans",
    METADATA,
    sa.Column("scan_id", UUID_TYPE, primary_key=True),
    sa.Column("case_id", sa.Text(), sa.ForeignKey("cases.case_id", ondelete="SET NULL"), nullable=True),
    sa.Column("url", sa.Text(), nullable=False),
    sa.Column("domain", sa.Text(), nullable=True),
    sa.Column("scan_type", sa.Text(), nullable=False, server_default="passive"),  # passive | active | full
    sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
    sa.Column("passive_result", JSON_TYPE, nullable=True),
    sa.Column("active_result", JSON_TYPE, nullable=True),
    sa.Column("classification_result", JSON_TYPE, nullable=True),
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
    sa.Column("metadata", JSON_TYPE, nullable=True),
    sa.Column("started_at", TIMESTAMP, nullable=True),
    sa.Column("completed_at", TIMESTAMP, nullable=True),
    sa.Column("normalized_url", sa.Text(), nullable=True),
    sa.Column("taken_down_at", TIMESTAMP, nullable=True),
    sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.Column("updated_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
)
sa.Index("idx_site_scans_case_id", site_scans.c.case_id)
sa.Index("idx_site_scans_domain", site_scans.c.domain)
sa.Index("idx_site_scans_status", site_scans.c.status)
sa.Index("idx_site_scans_created_at", site_scans.c.created_at)
sa.Index("idx_site_scans_risk_score", site_scans.c.risk_score)
sa.Index(
    "idx_site_scans_normalized_url",
    site_scans.c.normalized_url,
    site_scans.c.status,
    site_scans.c.completed_at,
)

case_investigations = sa.Table(
    "case_investigations",
    METADATA,
    sa.Column("case_id", sa.Text(), sa.ForeignKey("cases.case_id", ondelete="CASCADE"), nullable=False),
    sa.Column("scan_id", UUID_TYPE, sa.ForeignKey("site_scans.scan_id", ondelete="CASCADE"), nullable=False),
    sa.Column("trigger_type", sa.Text(), nullable=False, server_default="manual"),  # manual | auto | case_created
    sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.PrimaryKeyConstraint("case_id", "scan_id"),
)
sa.Index("idx_case_investigations_scan_id", case_investigations.c.scan_id)
sa.Index("idx_case_investigations_trigger_type", case_investigations.c.trigger_type)

harvested_wallets = sa.Table(
    "harvested_wallets",
    METADATA,
    sa.Column("wallet_id", UUID_TYPE, primary_key=True),
    sa.Column("scan_id", UUID_TYPE, sa.ForeignKey("site_scans.scan_id", ondelete="CASCADE"), nullable=False),
    sa.Column("case_id", sa.Text(), sa.ForeignKey("cases.case_id", ondelete="SET NULL"), nullable=True),
    sa.Column("token_label", sa.Text(), nullable=True),
    sa.Column("token_symbol", sa.Text(), nullable=False),
    sa.Column("network_label", sa.Text(), nullable=True),
    sa.Column("network_short", sa.Text(), nullable=False),
    sa.Column("wallet_address", sa.Text(), nullable=False),
    sa.Column("source", sa.Text(), nullable=False, server_default="js"),  # js | llm | opportunistic
    sa.Column("confidence", sa.Numeric(3, 2), nullable=False, server_default="0"),
    sa.Column("site_url", sa.Text(), nullable=True),
    sa.Column("metadata", JSON_TYPE, nullable=True),
    sa.Column("harvested_at", TIMESTAMP, nullable=True),
    sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.UniqueConstraint(
        "scan_id", "token_symbol", "network_short", "wallet_address", name="uq_wallets_scan_token_addr"
    ),
)
sa.Index("idx_wallets_scan_id", harvested_wallets.c.scan_id)
sa.Index("idx_wallets_case_id", harvested_wallets.c.case_id)
sa.Index("idx_wallets_address", harvested_wallets.c.wallet_address)
sa.Index("idx_wallets_token_symbol", harvested_wallets.c.token_symbol)

agent_sessions = sa.Table(
    "agent_sessions",
    METADATA,
    sa.Column("session_id", UUID_TYPE, primary_key=True),
    sa.Column("scan_id", UUID_TYPE, sa.ForeignKey("site_scans.scan_id", ondelete="CASCADE"), nullable=False),
    sa.Column("state", sa.Text(), nullable=False),
    sa.Column("action_type", sa.Text(), nullable=True),
    sa.Column("action_detail", JSON_TYPE, nullable=True),
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
    sa.Column("metadata", JSON_TYPE, nullable=True),
    sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
)
sa.Index("idx_agent_sessions_scan_id", agent_sessions.c.scan_id, agent_sessions.c.sequence)
sa.Index("idx_agent_sessions_state", agent_sessions.c.state)

pii_exposures = sa.Table(
    "pii_exposures",
    METADATA,
    sa.Column("exposure_id", UUID_TYPE, primary_key=True),
    sa.Column("scan_id", UUID_TYPE, sa.ForeignKey("site_scans.scan_id", ondelete="CASCADE"), nullable=False),
    sa.Column("case_id", sa.Text(), sa.ForeignKey("cases.case_id", ondelete="SET NULL"), nullable=True),
    sa.Column(
        "field_type", sa.Text(), nullable=False
    ),  # email | password | phone | name | address | ssn | id_number | financial | other
    sa.Column("field_label", sa.Text(), nullable=True),
    sa.Column("form_action", sa.Text(), nullable=True),
    sa.Column("page_url", sa.Text(), nullable=True),
    sa.Column("is_required", sa.Boolean(), nullable=True),
    sa.Column("was_submitted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    sa.Column("metadata", JSON_TYPE, nullable=True),
    sa.Column("detected_at", TIMESTAMP, nullable=True),
    sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
)
sa.Index("idx_pii_exposures_scan_id", pii_exposures.c.scan_id)
sa.Index("idx_pii_exposures_case_id", pii_exposures.c.case_id)
sa.Index("idx_pii_exposures_field_type", pii_exposures.c.field_type)

ssi_events = sa.Table(
    "ssi_events",
    METADATA,
    sa.Column("id", UUID_TYPE, primary_key=True),
    sa.Column(
        "scan_id",
        UUID_TYPE,
        sa.ForeignKey("site_scans.scan_id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("event_type", sa.Text(), nullable=False),
    sa.Column("timestamp", TIMESTAMP, nullable=False),
    # Carries all event data; screenshots are stored as inline base64 in this column.
    sa.Column("data_json", JSON_TYPE, nullable=True),
    # Reserved for future GCS-backed screenshots (nullable — base64 is stored in data_json).
    sa.Column("screenshot_url", sa.Text(), nullable=True),
    sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
)
sa.Index("idx_ssi_events_scan_id", ssi_events.c.scan_id)
sa.Index("idx_ssi_events_timestamp", ssi_events.c.scan_id, ssi_events.c.timestamp)
sa.Index("idx_ssi_events_event_type", ssi_events.c.event_type)

ssi_guidance_commands = sa.Table(
    "ssi_guidance_commands",
    METADATA,
    sa.Column("id", UUID_TYPE, primary_key=True),
    sa.Column(
        "scan_id",
        UUID_TYPE,
        sa.ForeignKey("site_scans.scan_id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("action", sa.Text(), nullable=False),
    sa.Column("value", sa.Text(), nullable=True, default=""),
    sa.Column("reason", sa.Text(), nullable=True, default=""),
    sa.Column("acknowledged", sa.Boolean(), nullable=False, default=False, server_default=sa.false()),
    sa.Column("acknowledged_at", TIMESTAMP, nullable=True),
    sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
)
sa.Index("idx_ssi_guidance_scan_id", ssi_guidance_commands.c.scan_id)
sa.Index(
    "idx_ssi_guidance_pending",
    ssi_guidance_commands.c.scan_id,
    ssi_guidance_commands.c.acknowledged,
    ssi_guidance_commands.c.created_at,
)

# ---------------------------------------------------------------------------
# TIFAP: Threat Intelligence & Fraud Analytics Platform tables
# ---------------------------------------------------------------------------

threat_campaigns = sa.Table(
    "threat_campaigns",
    METADATA,
    sa.Column("campaign_id", UUID_TYPE, primary_key=True),
    sa.Column("name", sa.Text(), nullable=False),
    sa.Column("description", sa.Text(), nullable=True),
    sa.Column("origin", sa.Text(), nullable=False, server_default="manual"),
    sa.Column("status", sa.Text(), nullable=False, server_default="emerging"),
    sa.Column("risk_score", sa.Numeric(5, 1), nullable=False, server_default="0"),
    sa.Column("taxonomy_rollup", JSON_TYPE, nullable=True),
    sa.Column("metadata", JSON_TYPE, nullable=True),
    sa.Column("created_by", sa.Text(), nullable=False, server_default="system"),
    sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.Column("updated_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
)
sa.Index("idx_threat_campaigns_status", threat_campaigns.c.status)
sa.Index("idx_threat_campaigns_risk_score", threat_campaigns.c.risk_score)

threat_campaign_cases = sa.Table(
    "threat_campaign_cases",
    METADATA,
    sa.Column(
        "campaign_id",
        UUID_TYPE,
        sa.ForeignKey("threat_campaigns.campaign_id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("case_id", sa.Text(), sa.ForeignKey("cases.case_id", ondelete="CASCADE"), nullable=False),
    sa.Column("linked_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.Column("linked_by", sa.Text(), nullable=False, server_default="manual"),
    sa.Column("link_reason", sa.Text(), nullable=True),
    sa.UniqueConstraint("campaign_id", "case_id", name="uq_threat_campaign_cases"),
)
sa.Index("idx_tcc_campaign_id", threat_campaign_cases.c.campaign_id)
sa.Index("idx_tcc_case_id", threat_campaign_cases.c.case_id)

intake_indicator_links = sa.Table(
    "intake_indicator_links",
    METADATA,
    sa.Column("intake_id", sa.Text(), sa.ForeignKey("intake_records.intake_id", ondelete="CASCADE"), nullable=False),
    sa.Column(
        "indicator_id",
        UUID_TYPE,
        sa.ForeignKey("indicators.indicator_id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("confidence", sa.Numeric(5, 4), nullable=False, server_default="0"),
    sa.Column("linked_by", sa.Text(), nullable=False, server_default="system"),
    sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.PrimaryKeyConstraint("intake_id", "indicator_id", name="pk_intake_indicator_links"),
)
sa.Index("idx_iil_indicator_id", intake_indicator_links.c.indicator_id)

entity_stats = sa.Table(
    "entity_stats",
    METADATA,
    sa.Column("entity_type", sa.Text(), nullable=False),
    sa.Column("canonical_value", sa.Text(), nullable=False),
    sa.Column("case_count", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("victim_count", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("loss_sum", sa.Numeric(14, 2), nullable=False, server_default="0"),
    sa.Column("loss_currency", sa.Text(), nullable=False, server_default="USD"),
    sa.Column("max_risk_score", sa.Numeric(5, 1), nullable=False, server_default="0"),
    sa.Column("avg_risk_score", sa.Numeric(5, 1), nullable=False, server_default="0"),
    sa.Column("first_seen_at", TIMESTAMP, nullable=True),
    sa.Column("last_seen_at", TIMESTAMP, nullable=True),
    sa.Column("status", sa.Text(), nullable=False, server_default="active"),
    sa.Column("campaign_ids", JSON_TYPE, nullable=True),
    sa.Column("top_classifications", JSON_TYPE, nullable=True),
    sa.Column("ecx_submitted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    sa.Column("ecx_hit", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    sa.Column("purge_status", sa.Text(), nullable=True),
    sa.Column("taken_down_at", TIMESTAMP, nullable=True),
    sa.Column("updated_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.PrimaryKeyConstraint("entity_type", "canonical_value", name="pk_entity_stats"),
)
sa.Index("idx_entity_stats_status", entity_stats.c.status)
sa.Index("idx_entity_stats_case_count", entity_stats.c.case_count)
sa.Index("idx_entity_stats_loss_sum", entity_stats.c.loss_sum)

indicator_stats = sa.Table(
    "indicator_stats",
    METADATA,
    sa.Column("indicator_id", UUID_TYPE, primary_key=True),
    sa.Column("category", sa.Text(), nullable=False),
    sa.Column("item", sa.Text(), nullable=True),
    sa.Column("type", sa.Text(), nullable=False),
    sa.Column("number", sa.Text(), nullable=False),
    sa.Column("case_count", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("loss_sum", sa.Numeric(14, 2), nullable=False, server_default="0"),
    sa.Column("first_seen_at", TIMESTAMP, nullable=True),
    sa.Column("last_seen_at", TIMESTAMP, nullable=True),
    sa.Column("max_risk_score", sa.Numeric(5, 1), nullable=False, server_default="0"),
    sa.Column("ecx_status", sa.Text(), nullable=False, server_default="not_submitted"),
    sa.Column("updated_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
)
sa.Index("idx_indicator_stats_category", indicator_stats.c.category)
sa.Index("idx_indicator_stats_case_count", indicator_stats.c.case_count)
sa.Index("idx_indicator_stats_first_seen_at", indicator_stats.c.first_seen_at)

campaign_stats = sa.Table(
    "campaign_stats",
    METADATA,
    sa.Column(
        "campaign_id",
        UUID_TYPE,
        sa.ForeignKey("threat_campaigns.campaign_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column("case_count", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("indicator_count", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("entity_types", JSON_TYPE, nullable=True),
    sa.Column("loss_sum", sa.Numeric(14, 2), nullable=False, server_default="0"),
    sa.Column("victim_count", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("risk_score", sa.Numeric(5, 1), nullable=False, server_default="0"),
    sa.Column("taxonomy_rollup", JSON_TYPE, nullable=True),
    sa.Column("first_case_at", TIMESTAMP, nullable=True),
    sa.Column("last_case_at", TIMESTAMP, nullable=True),
    sa.Column("status", sa.Text(), nullable=False, server_default="emerging"),
    sa.Column("updated_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
)
sa.Index("idx_campaign_stats_status", campaign_stats.c.status)
sa.Index("idx_campaign_stats_risk_score", campaign_stats.c.risk_score)

platform_kpis = sa.Table(
    "platform_kpis",
    METADATA,
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
    sa.Column("updated_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.PrimaryKeyConstraint("period_type", "period_start", name="pk_platform_kpis"),
)

annotations = sa.Table(
    "annotations",
    METADATA,
    sa.Column("annotation_id", UUID_TYPE, primary_key=True),
    sa.Column("target_type", sa.Text(), nullable=False),  # entity | indicator | campaign | case
    sa.Column("target_id", sa.Text(), nullable=False),
    sa.Column("content", sa.Text(), nullable=False),
    sa.Column("author", sa.Text(), nullable=False, server_default="system"),
    sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.Column("updated_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
)
sa.Index("idx_annotations_target", annotations.c.target_type, annotations.c.target_id)
sa.Index("idx_annotations_author", annotations.c.author)

# ---------------------------------------------------------------------------
# Watchlist (S5-04 / F-43)
# ---------------------------------------------------------------------------

watchlist_items = sa.Table(
    "watchlist_items",
    METADATA,
    sa.Column("watchlist_id", UUID_TYPE, primary_key=True),
    sa.Column("entity_type", sa.Text(), nullable=False),
    sa.Column("canonical_value", sa.Text(), nullable=False),
    sa.Column("alert_on_new_case", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    sa.Column("alert_on_loss_increase", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    sa.Column("loss_threshold", sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column("note", sa.Text(), nullable=True),
    sa.Column("created_by", sa.Text(), nullable=False, server_default="system"),
    sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.Column("updated_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
)
sa.Index("idx_watchlist_entity", watchlist_items.c.entity_type, watchlist_items.c.canonical_value, unique=True)
sa.Index("idx_watchlist_created_by", watchlist_items.c.created_by)

watchlist_alerts = sa.Table(
    "watchlist_alerts",
    METADATA,
    sa.Column("alert_id", UUID_TYPE, primary_key=True),
    sa.Column("watchlist_id", UUID_TYPE, nullable=False),
    sa.Column("alert_type", sa.Text(), nullable=False),  # new_case | loss_increase
    sa.Column("message", sa.Text(), nullable=False),
    sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    sa.Column("data", JSON_TYPE, nullable=True),
    sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
)
sa.Index("idx_watchlist_alerts_watchlist", watchlist_alerts.c.watchlist_id)
sa.Index("idx_watchlist_alerts_unread", watchlist_alerts.c.is_read)

# ---------------------------------------------------------------------------
# Infrastructure edges (S5-08 / F-44)
# ---------------------------------------------------------------------------

infrastructure_edges = sa.Table(
    "infrastructure_edges",
    METADATA,
    sa.Column("edge_id", UUID_TYPE, primary_key=True),
    sa.Column("source_entity_type", sa.Text(), nullable=False),
    sa.Column("source_canonical_value", sa.Text(), nullable=False),
    sa.Column("target_entity_type", sa.Text(), nullable=False),
    sa.Column("target_canonical_value", sa.Text(), nullable=False),
    sa.Column("edge_type", sa.Text(), nullable=False),  # shared_ip | shared_registrar | shared_hosting
    sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=False, server_default="1.0"),
    sa.Column("evidence", JSON_TYPE, nullable=True),
    sa.Column("discovered_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
)
sa.Index(
    "idx_infra_edges_source", infrastructure_edges.c.source_entity_type, infrastructure_edges.c.source_canonical_value
)
sa.Index(
    "idx_infra_edges_target", infrastructure_edges.c.target_entity_type, infrastructure_edges.c.target_canonical_value
)

# ---------------------------------------------------------------------------
# Scheduled reports (S5-14 / F-47)
# ---------------------------------------------------------------------------

scheduled_reports = sa.Table(
    "scheduled_reports",
    METADATA,
    sa.Column("schedule_id", UUID_TYPE, primary_key=True),
    sa.Column("template", sa.Text(), nullable=False),
    sa.Column("cadence", sa.Text(), nullable=False),  # weekly | monthly
    sa.Column("scope", JSON_TYPE, nullable=True),
    sa.Column("options", JSON_TYPE, nullable=True),
    sa.Column("recipients", JSON_TYPE, nullable=True),
    sa.Column("created_by", sa.Text(), nullable=False),
    sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    sa.Column("last_run_at", TIMESTAMP, nullable=True),
    sa.Column("next_run_at", TIMESTAMP, nullable=True),
    sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default=sa.text("0")),
    sa.Column("last_error", sa.Text(), nullable=True),
    sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    sa.Column("updated_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
)
sa.Index("idx_scheduled_reports_active", scheduled_reports.c.is_active)
sa.Index("idx_scheduled_reports_next_run", scheduled_reports.c.next_run_at)

# ---------------------------------------------------------------------------
# Embeddable chart tokens (S5-17 / F-48)
# ---------------------------------------------------------------------------

chart_share_tokens = sa.Table(
    "chart_share_tokens",
    METADATA,
    sa.Column("token_id", UUID_TYPE, primary_key=True),
    sa.Column("chart_type", sa.Text(), nullable=False),
    sa.Column("chart_config", JSON_TYPE, nullable=False),
    sa.Column("created_by", sa.Text(), nullable=False),
    sa.Column("expires_at", TIMESTAMP, nullable=False),
    sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
)
sa.Index("idx_chart_tokens_expires", chart_share_tokens.c.expires_at)

# ---------------------------------------------------------------------------
# Partner indicator feed (S6-09, S6-10, S6-11)
# ---------------------------------------------------------------------------

partner_api_keys = sa.Table(
    "partner_api_keys",
    METADATA,
    sa.Column("key_id", UUID_TYPE, primary_key=True),
    sa.Column("partner_name", sa.Text(), nullable=False),
    sa.Column("key_hash", sa.Text(), nullable=False),
    sa.Column("key_prefix", sa.String(length=8), nullable=False),
    sa.Column("scopes", JSON_TYPE, nullable=True),
    sa.Column("rate_limit_per_minute", sa.Integer(), nullable=False, server_default=sa.text("60")),
    sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    sa.Column("created_by", sa.Text(), nullable=False),
    sa.Column("last_used_at", TIMESTAMP, nullable=True),
    sa.Column("expires_at", TIMESTAMP, nullable=True),
    sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
)
sa.Index("idx_partner_keys_prefix", partner_api_keys.c.key_prefix)
sa.Index("idx_partner_keys_active", partner_api_keys.c.is_active)

partner_feed_audit = sa.Table(
    "partner_feed_audit",
    METADATA,
    sa.Column("audit_id", UUID_TYPE, primary_key=True),
    sa.Column("key_id", UUID_TYPE, nullable=False),
    sa.Column("partner_name", sa.Text(), nullable=False),
    sa.Column("endpoint", sa.Text(), nullable=False),
    sa.Column("method", sa.Text(), nullable=False),
    sa.Column("query_params", JSON_TYPE, nullable=True),
    sa.Column("result_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    sa.Column("response_code", sa.Integer(), nullable=False),
    sa.Column("ip_address", sa.Text(), nullable=True),
    sa.Column("created_at", TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
)
sa.Index("idx_partner_audit_key", partner_feed_audit.c.key_id)
sa.Index("idx_partner_audit_created", partner_feed_audit.c.created_at)


def dialect_insert(session: Session, table: sa.Table):
    """Return a dialect-aware INSERT construct that supports ``on_conflict_do_update``.

    Both SQLite and PostgreSQL dialects offer ``insert(...).on_conflict_do_update()``.
    This helper picks the correct one based on the session's bound engine dialect.
    """

    bind = session.get_bind()
    dialect_name = bind.dialect.name
    if dialect_name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return insert(table)


def _resolve_database_url(settings: Settings | None = None) -> str:
    """Return the SQLAlchemy URL considering overrides and configured backend."""

    url_override = os.getenv("I4G_DATABASE_URL") or os.getenv("ALEMBIC_DATABASE_URL")
    if url_override:
        return url_override

    resolved = settings or get_settings()
    backend = resolved.storage.structured_backend
    if backend == "sqlite":
        sqlite_path = Path(resolved.storage.sqlite_path)
        return URL.create("sqlite", database=sqlite_path.as_posix()).render_as_string(hide_password=False)

    if backend == "cloudsql":
        raise NotImplementedError("Cloud SQL backend wiring not implemented yet")

    raise NotImplementedError(f"Unsupported structured backend '{backend}' for SQL engine creation")


_ENGINE_CACHE: dict[tuple, Engine] = {}


def build_engine(
    *,
    echo: bool = False,
    settings: Settings | None = None,
    backend_override: str | None = None,
    connection_details: dict[str, Any] | None = None,
) -> Engine:
    """Instantiate a SQLAlchemy engine aligned with project settings.

    Args:
        echo: Whether to log SQL statements.
        settings: Optional settings object.
        backend_override: Force a specific backend (e.g., 'cloudsql').
        connection_details: Optional dictionary with 'instance', 'user', 'password', 'database', 'enable_iam_auth'.
    """

    resolved = settings or get_settings()
    backend = backend_override or resolved.storage.structured_backend

    # Create cache key based on relevant connection parameters
    # Note: Settings object itself is not hashable, we assume if it's passed it might be different
    # but for the default case (None), we rely on the global get_settings() which we assume is stable per-env.
    # We include backend and connection details in the key.
    cache_key = (
        backend,
        echo,
        tuple(sorted(connection_details.items())) if connection_details else None,
        # We don't cache on settings object identity as it changes, but we assume
        # for a given process the effective config is stable for the default case.
        # If settings IS provided explicitly, we skip caching to be safe, or we'd need to hash it.
        # For now, we only cache when settings is None to fix the per-request overhead in the main app.
        settings is None,
    )

    if settings is None and cache_key in _ENGINE_CACHE:
        return _ENGINE_CACHE[cache_key]

    if backend == "cloudsql":
        from google.cloud.sql.connector import Connector, IPTypes

        details = connection_details or {}
        instance_connection_name = details.get("instance") or resolved.storage.cloudsql_instance
        db_user = details.get("user") or resolved.storage.cloudsql_user
        db_pass = details.get("password") or resolved.storage.cloudsql_password
        db_name = details.get("database") or resolved.storage.cloudsql_database
        enable_iam_auth = details.get("enable_iam_auth", resolved.storage.cloudsql_enable_iam_auth)

        # Password is not required if IAM auth is enabled
        if not all([instance_connection_name, db_user, db_name]) or (not enable_iam_auth and not db_pass):
            raise ValueError("Missing Cloud SQL configuration (instance, user, [password], database)")

        resolved_instance_connection_name = str(instance_connection_name)
        resolved_db_user = str(db_user)
        resolved_db_name = str(db_name)
        resolved_db_pass = str(db_pass) if db_pass is not None else None

        # Initialize Connector object
        # Note: Connector must be long-lived to avoid excessive API calls and thread creation
        connector = Connector()

        def getconn():
            conn = connector.connect(
                resolved_instance_connection_name,
                "pg8000",
                user=resolved_db_user,
                password=resolved_db_pass,
                db=resolved_db_name,
                ip_type=IPTypes.PUBLIC,
                enable_iam_auth=enable_iam_auth,
            )
            return conn

        engine = sa.create_engine(
            "postgresql+pg8000://",
            creator=getconn,
            echo=echo,
            future=True,
            pool_pre_ping=True,
        )

        if settings is None:
            _ENGINE_CACHE[cache_key] = engine
        return engine

    url = _resolve_database_url(resolved)
    connect_args: dict[str, Any] = {}
    if url.startswith("sqlite:///"):
        connect_args["check_same_thread"] = False

    engine = sa.create_engine(url, echo=echo, future=True, pool_pre_ping=True, connect_args=connect_args)

    if settings is None:
        _ENGINE_CACHE[cache_key] = engine
    return engine


def session_factory(
    *,
    settings: Settings | None = None,
    backend_override: str | None = None,
    connection_details: dict[str, Any] | None = None,
) -> sessionmaker:
    """Return a configured sessionmaker bound to the active engine."""

    engine = build_engine(
        settings=settings,
        backend_override=backend_override,
        connection_details=connection_details,
    )
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def build_vault_session_factory(
    *,
    settings: Settings | None = None,
    backend_override: str | None = None,
    connection_details: dict[str, Any] | None = None,
) -> sessionmaker:
    """Return a sessionmaker for the PII vault database.

    For SQLite, the vault database lives alongside the main store as
    ``vault.db``.  For Cloud SQL, the caller passes explicit connection
    details pointing to the isolated PII project.
    """

    resolved = settings or get_settings()
    backend = backend_override or resolved.pii.backend

    if backend == "cloudsql":
        engine = build_engine(
            settings=settings,
            backend_override="cloudsql",
            connection_details=connection_details,
        )
    else:
        # SQLite: vault.db lives next to the main SQLite store
        sqlite_path = Path(resolved.storage.sqlite_path)
        if not sqlite_path.is_absolute():
            sqlite_path = (Path(resolved.project_root) / sqlite_path).resolve()
        vault_path = sqlite_path.parent / "vault.db"
        vault_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{vault_path.as_posix()}"
        engine = sa.create_engine(
            url,
            future=True,
            pool_pre_ping=True,
            connect_args={"check_same_thread": False},
        )
        # Ensure vault tables exist for local development
        VAULT_METADATA.create_all(engine, checkfirst=True)

    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
