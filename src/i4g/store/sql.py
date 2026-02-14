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
    sa.Column("metadata", JSON_TYPE, nullable=True),
    sa.Column("created_at", TIMESTAMP, nullable=True),
    sa.Column("updated_at", TIMESTAMP, nullable=True),
)

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
