"""Ingestion/search/report/job section models."""

from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from i4g.settings.sections._paths import PROJECT_ROOT


class IngestionSettings(BaseSettings):
    """Scheduler + job configuration for ingestion workflows."""

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    enable_scheduled_jobs: bool = Field(
        default=False,
        validation_alias=AliasChoices("INGESTION_ENABLE_SCHEDULED_JOBS", "INGESTION__ENABLE_SCHEDULED_JOBS"),
    )
    default_region: str = Field(
        default="us-central1",
        validation_alias=AliasChoices("INGESTION_DEFAULT_REGION", "INGESTION__DEFAULT_REGION"),
    )
    scheduler_project: str | None = Field(
        default=None,
        validation_alias=AliasChoices("INGESTION_SCHEDULER_PROJECT", "INGESTION__SCHEDULER_PROJECT"),
    )
    default_service_account: str | None = Field(
        default=None,
        validation_alias=AliasChoices("INGESTION_SERVICE_ACCOUNT", "INGESTION__SERVICE_ACCOUNT"),
    )
    enable_sql: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "INGEST_ENABLE_SQL",
            "INGEST__ENABLE_SQL",
            "INGESTION_ENABLE_SQL",
            "INGESTION__ENABLE_SQL",
        ),
    )
    enable_vertex: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "INGEST_ENABLE_VERTEX",
            "INGEST__ENABLE_VERTEX",
            "INGESTION_ENABLE_VERTEX",
            "INGESTION__ENABLE_VERTEX",
        ),
    )
    enable_vector_store: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "INGEST_ENABLE_VECTOR",
            "INGEST__ENABLE_VECTOR",
            "INGESTION_ENABLE_VECTOR",
            "INGESTION__ENABLE_VECTOR",
        ),
    )
    dataset_path: str | Path = Field(
        default=PROJECT_ROOT / "data" / "retrieval_poc" / "cases.jsonl",
        validation_alias=AliasChoices(
            "INGEST_JSONL_PATH",
            "INGEST__JSONL_PATH",
            "INGESTION_JSONL_PATH",
            "INGESTION__JSONL_PATH",
        ),
    )
    batch_limit: int = Field(
        default=0,
        validation_alias=AliasChoices(
            "INGEST_BATCH_LIMIT",
            "INGEST__BATCH_LIMIT",
            "INGESTION_BATCH_LIMIT",
            "INGESTION__BATCH_LIMIT",
        ),
    )
    dry_run: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "INGEST_DRY_RUN",
            "INGEST__DRY_RUN",
            "INGESTION_DRY_RUN",
            "INGESTION__DRY_RUN",
        ),
    )
    reset_vector: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "INGEST_RESET_VECTOR",
            "INGEST__RESET_VECTOR",
            "INGESTION_RESET_VECTOR",
            "INGESTION__RESET_VECTOR",
        ),
    )
    default_dataset: str = Field(
        default="unknown",
        validation_alias=AliasChoices(
            "INGEST_DEFAULT_DATASET",
            "INGEST__DEFAULT_DATASET",
            "INGEST__DATASET_NAME",
            "INGESTION_DEFAULT_DATASET",
            "INGESTION__DEFAULT_DATASET",
        ),
    )
    fanout_timeout_seconds: int = Field(
        default=60,
        validation_alias=AliasChoices(
            "INGEST_FANOUT_TIMEOUT_SECONDS",
            "INGEST__FANOUT_TIMEOUT_SECONDS",
            "INGESTION_FANOUT_TIMEOUT_SECONDS",
            "INGESTION__FANOUT_TIMEOUT_SECONDS",
        ),
    )
    max_retries: int = Field(
        default=3,
        validation_alias=AliasChoices(
            "INGEST_MAX_RETRIES",
            "INGEST__MAX_RETRIES",
            "INGESTION_MAX_RETRIES",
            "INGESTION__MAX_RETRIES",
        ),
    )
    retry_delay_seconds: int = Field(
        default=60,
        validation_alias=AliasChoices(
            "INGEST_RETRY_DELAY_SECONDS",
            "INGEST__RETRY_DELAY_SECONDS",
            "INGESTION_RETRY_DELAY_SECONDS",
            "INGESTION__RETRY_DELAY_SECONDS",
        ),
    )
    rate_limit_delay: float = Field(
        default=0.0,
        validation_alias=AliasChoices(
            "INGEST_RATE_LIMIT_DELAY",
            "INGEST__RATE_LIMIT_DELAY",
            "INGESTION_RATE_LIMIT_DELAY",
            "INGESTION__RATE_LIMIT_DELAY",
        ),
        description="Delay in seconds between records for rate limiting.",
    )
    skip_classification: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "INGEST_SKIP_CLASSIFICATION",
            "INGEST__SKIP_CLASSIFICATION",
            "INGESTION_SKIP_CLASSIFICATION",
            "INGESTION__SKIP_CLASSIFICATION",
        ),
        description="When True, skip fraud classification during ingestion.",
    )


class IngestRetryJobSettings(BaseSettings):
    """Cloud Run job overrides for the ingestion retry processor."""

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    batch_limit: int = Field(
        default=25,
        validation_alias=AliasChoices("INGEST_RETRY_BATCH_LIMIT", "INGEST_RETRY__BATCH_LIMIT"),
    )
    dry_run: bool = Field(
        default=False,
        validation_alias=AliasChoices("INGEST_RETRY_DRY_RUN", "INGEST_RETRY__DRY_RUN"),
    )


class SweepSettings(BaseSettings):
    """Classification sweeper job configuration."""

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    max_runtime_seconds: int = Field(
        default=3300,
        validation_alias=AliasChoices(
            "SWEEP_MAX_RUNTIME_SECONDS",
            "SWEEP__MAX_RUNTIME_SECONDS",
            "JOB_MAX_RUNTIME_SECONDS",
        ),
        description="Maximum wall-clock seconds before the sweeper exits gracefully.",
    )
    batch_size: int = Field(
        default=20,
        validation_alias=AliasChoices(
            "SWEEP_BATCH_SIZE",
            "SWEEP__BATCH_SIZE",
            "JOB_BATCH_SIZE",
        ),
        description="Number of cases to classify per loop iteration.",
    )


class DossierJobSettings(BaseSettings):
    """Cloud Run job overrides for dossier queue processing."""

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    batch_size: int = Field(
        default=5,
        validation_alias=AliasChoices("DOSSIER_BATCH_SIZE", "DOSSIER__BATCH_SIZE"),
    )
    dry_run: bool = Field(
        default=False,
        validation_alias=AliasChoices("DOSSIER_DRY_RUN", "DOSSIER__DRY_RUN"),
    )


class SmokeSettings(BaseSettings):
    """Smoke test CLI defaults."""

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    api_url: str = Field(
        default="https://core-svc-y5jge5w2cq-uc.a.run.app",
        validation_alias=AliasChoices("SMOKE_API_URL", "SMOKE__API_URL"),
        description="Default API base URL for smoke tests.",
    )


class ObservabilitySettings(BaseSettings):
    """Logging, tracing, and metrics configuration."""

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    structured_logging: bool = Field(
        default=True,
        validation_alias=AliasChoices("OBS_STRUCTURED_LOGGING", "OBSERVABILITY__STRUCTURED_LOGGING"),
    )
    otlp_endpoint: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OBS_OTLP_ENDPOINT", "OBSERVABILITY__OTLP_ENDPOINT"),
    )
    trace_sample_rate: float = Field(
        default=0.0,
        validation_alias=AliasChoices("OBS_TRACE_SAMPLE_RATE", "OBSERVABILITY__TRACE_SAMPLE_RATE"),
    )
    statsd_host: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OBS_STATSD_HOST", "OBSERVABILITY__STATSD_HOST"),
    )
    statsd_port: int = Field(
        default=8125,
        validation_alias=AliasChoices("OBS_STATSD_PORT", "OBSERVABILITY__STATSD_PORT"),
    )
    statsd_prefix: str = Field(
        default="i4g",
        validation_alias=AliasChoices("OBS_STATSD_PREFIX", "OBSERVABILITY__STATSD_PREFIX"),
    )
    service_name: str = Field(
        default="i4g-backend",
        validation_alias=AliasChoices("OBS_SERVICE_NAME", "OBSERVABILITY__SERVICE_NAME"),
    )

    # Alerting thresholds (F48–F50)
    detokenization_alert_threshold: int = Field(
        default=10,
        description="Max detokenization calls per user per hour before alerting.",
        validation_alias=AliasChoices(
            "OBS_DETOKENIZATION_ALERT_THRESHOLD",
            "OBSERVABILITY__DETOKENIZATION_ALERT_THRESHOLD",
        ),
    )
    ingestion_error_rate_threshold: float = Field(
        default=0.10,
        description="Ingestion failure rate (0.0–1.0) that triggers an alert.",
        validation_alias=AliasChoices(
            "OBS_INGESTION_ERROR_RATE_THRESHOLD",
            "OBSERVABILITY__INGESTION_ERROR_RATE_THRESHOLD",
        ),
    )
    dossier_stuck_timeout_minutes: int = Field(
        default=30,
        description="Minutes after which a dossier job is considered stuck.",
        validation_alias=AliasChoices(
            "OBS_DOSSIER_STUCK_TIMEOUT_MINUTES",
            "OBSERVABILITY__DOSSIER_STUCK_TIMEOUT_MINUTES",
        ),
    )


class AccountListSettings(BaseSettings):
    """Account list extraction configuration."""

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("ACCOUNT_LIST_ENABLED", "ACCOUNT_LIST__ENABLED"),
    )
    require_api_key: bool = Field(
        default=True,
        validation_alias=AliasChoices("ACCOUNT_LIST_REQUIRE_API_KEY", "ACCOUNT_LIST__REQUIRE_API_KEY"),
    )
    api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ACCOUNT_LIST_API_KEY", "ACCOUNT_LIST__API_KEY"),
    )
    header_name: str = Field(
        default="X-ACCOUNTLIST-KEY",
        validation_alias=AliasChoices("ACCOUNT_LIST_HEADER_NAME", "ACCOUNT_LIST__HEADER_NAME"),
    )
    max_top_k: int = Field(
        default=250,
        validation_alias=AliasChoices("ACCOUNT_LIST_MAX_TOP_K", "ACCOUNT_LIST__MAX_TOP_K"),
    )
    default_formats: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("ACCOUNT_LIST_DEFAULT_FORMATS", "ACCOUNT_LIST__DEFAULT_FORMATS"),
    )
    artifact_prefix: str = Field(
        default="account_list",
        validation_alias=AliasChoices("ACCOUNT_LIST_ARTIFACT_PREFIX", "ACCOUNT_LIST__ARTIFACT_PREFIX"),
    )
    drive_folder_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ACCOUNT_LIST_DRIVE_FOLDER_ID", "ACCOUNT_LIST__DRIVE_FOLDER_ID"),
    )
    enable_vector: bool = Field(
        default=True,
        validation_alias=AliasChoices("ACCOUNT_LIST_ENABLE_VECTOR", "ACCOUNT_LIST__ENABLE_VECTOR"),
    )


class SavedSearchSettings(BaseSettings):
    """Saved-search migration defaults shared across CLI scripts."""

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    migration_tag: str = Field(
        default="hybrid-v1",
        validation_alias=AliasChoices(
            "SEARCH_SAVED_SEARCH_MIGRATION_TAG",
            "SEARCH__SAVED_SEARCH__MIGRATION_TAG",
            "SAVED_SEARCH_MIGRATION_TAG",
        ),
    )
    schema_version: str = Field(
        default="",
        validation_alias=AliasChoices(
            "SEARCH_SAVED_SEARCH_SCHEMA_VERSION",
            "SEARCH__SAVED_SEARCH__SCHEMA_VERSION",
            "SAVED_SEARCH_SCHEMA_VERSION",
        ),
    )


class SearchSettings(BaseSettings):
    """Hybrid search tuning parameters and schema presets."""

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    semantic_weight: float = Field(
        default=0.65,
        validation_alias=AliasChoices("SEARCH_SEMANTIC_WEIGHT", "SEARCH__SEMANTIC_WEIGHT"),
    )
    structured_weight: float = Field(
        default=0.35,
        validation_alias=AliasChoices("SEARCH_STRUCTURED_WEIGHT", "SEARCH__STRUCTURED_WEIGHT"),
    )
    default_limit: int = Field(
        default=25,
        validation_alias=AliasChoices("SEARCH_DEFAULT_LIMIT", "SEARCH__DEFAULT_LIMIT"),
    )
    schema_cache_ttl_seconds: int = Field(
        default=300,
        validation_alias=AliasChoices("SEARCH_SCHEMA_CACHE_TTL", "SEARCH__SCHEMA_CACHE_TTL"),
    )
    indicator_types: list[str] = Field(
        default_factory=lambda: [
            "bank_account",
            "crypto_wallet",
            "email",
            "phone",
            "ip_address",
            "asn",
            "browser_agent",
            "url",
            "merchant",
        ],
        validation_alias=AliasChoices("SEARCH_INDICATOR_TYPES", "SEARCH__INDICATOR_TYPES"),
    )
    dataset_presets: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("SEARCH_DATASET_PRESETS", "SEARCH__DATASET_PRESETS"),
    )
    classification_presets: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("SEARCH_CLASSIFICATION_PRESETS", "SEARCH__CLASSIFICATION_PRESETS"),
    )
    time_presets: list[str] = Field(
        default_factory=lambda: ["7d", "30d", "90d"],
        validation_alias=AliasChoices("SEARCH_TIME_PRESETS", "SEARCH__TIME_PRESETS"),
    )
    loss_buckets: list[str] = Field(
        default_factory=lambda: ["<10k", "10k-50k", ">50k"],
        validation_alias=AliasChoices("SEARCH_LOSS_BUCKETS", "SEARCH__LOSS_BUCKETS"),
    )
    schema_entity_example_limit: int = Field(
        default=5,
        validation_alias=AliasChoices("SEARCH_SCHEMA_ENTITY_EXAMPLE_LIMIT", "SEARCH__SCHEMA_ENTITY_EXAMPLE_LIMIT"),
    )
    saved_search: SavedSearchSettings = Field(default_factory=SavedSearchSettings)

    @model_validator(mode="after")
    def _validate_weights(self) -> SearchSettings:
        """Ensure semantic/structured weights fall within acceptable bounds."""

        for field_name in ("semantic_weight", "structured_weight"):
            value = getattr(self, field_name)
            if value < 0 or value > 1:
                raise ValueError(f"{field_name} must be between 0 and 1 inclusive (got {value})")
        if self.semantic_weight == 0 and self.structured_weight == 0:
            raise ValueError("At least one of semantic_weight or structured_weight must be greater than zero.")
        return self


class ReportSettings(BaseSettings):
    """Agentic dossier/report configuration."""

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    drive_parent_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("REPORT_DRIVE_PARENT_ID", "REPORT__DRIVE_PARENT_ID"),
    )
    min_loss_usd: float = Field(
        default=50000.0,
        validation_alias=AliasChoices("REPORT_MIN_LOSS_USD", "REPORT__MIN_LOSS_USD"),
    )
    recency_days: int = Field(
        default=30,
        validation_alias=AliasChoices("REPORT_RECENCY_DAYS", "REPORT__RECENCY_DAYS"),
    )
    max_cases_per_dossier: int = Field(
        default=5,
        validation_alias=AliasChoices("REPORT_MAX_CASES_PER_DOSSIER", "REPORT__MAX_CASES_PER_DOSSIER"),
    )
    require_cross_border: bool = Field(
        default=False,
        validation_alias=AliasChoices("REPORT_REQUIRE_CROSS_BORDER", "REPORT__REQUIRE_CROSS_BORDER"),
    )
    hash_algorithm: str = Field(
        default="sha256",
        validation_alias=AliasChoices("REPORT_HASH_ALGORITHM", "REPORT__HASH_ALGORITHM"),
    )
    tool_timeout_seconds: float | None = Field(
        default=None,
        validation_alias=AliasChoices("REPORT_TOOL_TIMEOUT_SECONDS", "REPORT__TOOL_TIMEOUT_SECONDS"),
        description="Per-tool timeout for LangChain dossier tools; None disables timeouts.",
    )
    batch_limit: int = Field(
        default=25,
        validation_alias=AliasChoices("REPORT_BATCH_LIMIT", "REPORT__BATCH_LIMIT"),
        description="Maximum number of reviews to process per report batch.",
    )
    target_status: str = Field(
        default="accepted",
        validation_alias=AliasChoices("REPORT_TARGET_STATUS", "REPORT__TARGET_STATUS"),
        description="Queue status filter when auto-resolving review IDs.",
    )
    review_ids: str | None = Field(
        default=None,
        validation_alias=AliasChoices("REPORT_REVIEW_IDS", "REPORT__REVIEW_IDS"),
        description="Comma-separated explicit review IDs (overrides queue lookup).",
    )
    dry_run: bool = Field(
        default=False,
        validation_alias=AliasChoices("REPORT_DRY_RUN", "REPORT__DRY_RUN"),
        description="When True, log actions without generating reports.",
    )


class AccountJobSettings(BaseSettings):
    """Cloud Run job overrides for account list extraction."""

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    output_formats: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("ACCOUNT_JOB_OUTPUT_FORMATS", "ACCOUNT_JOB__OUTPUT_FORMATS"),
        description="Comma-separated output formats (e.g. pdf,xlsx). Overrides account_list.default_formats.",
    )
    start_time: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ACCOUNT_JOB_START_TIME", "ACCOUNT_JOB__START_TIME"),
        description="ISO-8601 start of the extraction window. Defaults to end_time minus window_days.",
    )
    end_time: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ACCOUNT_JOB_END_TIME", "ACCOUNT_JOB__END_TIME"),
        description="ISO-8601 end of the extraction window. Defaults to now (UTC).",
    )
    window_days: int = Field(
        default=15,
        validation_alias=AliasChoices("ACCOUNT_JOB_WINDOW_DAYS", "ACCOUNT_JOB__WINDOW_DAYS"),
        description="Number of days in the extraction window when start_time is not set.",
    )
    categories: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("ACCOUNT_JOB_CATEGORIES", "ACCOUNT_JOB__CATEGORIES"),
        description="Comma-separated fraud categories to include (e.g. bank,crypto,payments).",
    )
    top_k: int = Field(
        default=200,
        validation_alias=AliasChoices("ACCOUNT_JOB_TOP_K", "ACCOUNT_JOB__TOP_K"),
        description="Maximum number of accounts to extract per run.",
    )
    include_sources: bool = Field(
        default=True,
        validation_alias=AliasChoices("ACCOUNT_JOB_INCLUDE_SOURCES", "ACCOUNT_JOB__INCLUDE_SOURCES"),
        description="Whether to include source evidence references in output.",
    )
    dry_run: bool = Field(
        default=False,
        validation_alias=AliasChoices("ACCOUNT_JOB_DRY_RUN", "ACCOUNT_JOB__DRY_RUN"),
        description="Run extraction without persisting results.",
    )


class IntakeJobSettings(BaseSettings):
    """Cloud Run job overrides for intake processing."""

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("INTAKE_ID", "INTAKE__ID"),
        description="Intake submission ID to process.",
    )
    job_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("INTAKE_JOB_ID", "INTAKE__JOB_ID"),
        description="Intake job ID for tracking.",
    )
    api_base: str | None = Field(
        default=None,
        validation_alias=AliasChoices("INTAKE_API_BASE", "INTAKE__API_BASE"),
        description="Base URL for the intake API (if processing via HTTP rather than direct service call).",
    )
    api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("INTAKE_API_KEY", "INTAKE__API_KEY"),
        description="API key for authenticating intake API calls. Falls back to api.key.",
    )


class SsiSettings(BaseSettings):
    """Configuration for triggering SSI investigations from the core API.

    Used by ``POST /investigations/ssi`` to launch an SSI investigation
    via the SSI Cloud Run Service and track its progress.
    """

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    service_url: str = Field(
        default="",
        validation_alias=AliasChoices("SSI_SERVICE_URL", "SSI__SERVICE_URL"),
        description="Base URL of the SSI Cloud Run Service.",
    )
    core_api_url: str = Field(
        default="https://api.dev.intelligenceforgood.org",
        validation_alias=AliasChoices("SSI_CORE_API_URL", "SSI__CORE_API_URL"),
        description="Core API base URL for task status callbacks from the SSI service.",
    )
    playbook_dir: str = Field(
        default="config/playbooks",
        validation_alias=AliasChoices("SSI_PLAYBOOK_DIR", "SSI__PLAYBOOK_DIR"),
        description="Directory containing SSI playbook JSON files. Resolved relative to project root.",
    )
    events_endpoint: str = Field(
        default="",
        validation_alias=AliasChoices("SSI_EVENTS_ENDPOINT", "SSI__EVENTS_ENDPOINT"),
        description="Core API endpoint prefix for pushing SSI events (e.g. https://api.example.com). Empty disables HTTP event sink.",  # noqa: E501
    )


class RedisSettings(BaseSettings):
    """Optional Redis connection for SSE pub/sub fan-out.

    When ``url`` is empty (the default), Redis is disabled and the SSE
    endpoint falls back to polling the ``ssi_events`` table directly.
    Cloud Memorystore (Basic tier, 1 GB) is recommended for production.

    Env vars: ``I4G_REDIS__URL``, ``I4G_REDIS__CHANNEL_PREFIX``.
    """

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    url: str = Field(
        default="",
        validation_alias=AliasChoices("REDIS_URL", "REDIS__URL"),
        description="Redis connection URL (e.g. redis://localhost:6379/0). Empty disables Redis.",
    )
    channel_prefix: str = Field(
        default="ssi:events",
        validation_alias=AliasChoices("REDIS_CHANNEL_PREFIX", "REDIS__CHANNEL_PREFIX"),
        description="Pub/sub channel prefix for SSI events. Full channel: {prefix}:{scan_id}.",
    )
    poll_interval_seconds: float = Field(
        default=2.0,
        validation_alias=AliasChoices("REDIS_POLL_INTERVAL", "REDIS__POLL_INTERVAL"),
        description="DB polling interval (seconds) when Redis is unavailable.",
    )


class AnalyticsSettings(BaseSettings):
    """Threat-intelligence analytics aggregation configuration.

    Controls the scheduled aggregation job that populates the pre-computed
    ``entity_stats``, ``indicator_stats``, ``campaign_stats``, and
    ``platform_kpis`` tables.

    Env vars: ``I4G_ANALYTICS__REFRESH_INTERVAL_MINUTES``, etc.
    """

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    refresh_interval_minutes: int = Field(
        default=15,
        validation_alias=AliasChoices("ANALYTICS_REFRESH_INTERVAL_MINUTES", "ANALYTICS__REFRESH_INTERVAL_MINUTES"),
        description="Minutes between automatic aggregation refreshes.",
    )
    loss_linkage_confidence_threshold: float = Field(
        default=0.6,
        validation_alias=AliasChoices(
            "ANALYTICS_LOSS_LINKAGE_CONFIDENCE_THRESHOLD",
            "ANALYTICS__LOSS_LINKAGE_CONFIDENCE_THRESHOLD",
        ),
        description="Minimum LLM confidence for intake-indicator link acceptance (0.0–1.0).",
    )
    campaign_risk_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "case_count": 0.15,
            "loss_sum": 0.30,
            "avg_risk": 0.25,
            "recency": 0.15,
            "indicator_diversity": 0.15,
        },
        validation_alias=AliasChoices("ANALYTICS_CAMPAIGN_RISK_WEIGHTS", "ANALYTICS__CAMPAIGN_RISK_WEIGHTS"),
        description="Weight factors for campaign risk score computation.",
    )

    # Sprint 5 — watchlist, infrastructure clustering, scheduled reports
    watchlist_check_interval_minutes: int = Field(
        default=30,
        validation_alias=AliasChoices(
            "ANALYTICS_WATCHLIST_CHECK_INTERVAL_MINUTES",
            "ANALYTICS__WATCHLIST_CHECK_INTERVAL_MINUTES",
        ),
        description="Minutes between watchlist notification checks.",
    )
    infrastructure_clustering_interval_hours: int = Field(
        default=6,
        validation_alias=AliasChoices(
            "ANALYTICS_INFRASTRUCTURE_CLUSTERING_INTERVAL_HOURS",
            "ANALYTICS__INFRASTRUCTURE_CLUSTERING_INTERVAL_HOURS",
        ),
        description="Hours between infrastructure clustering runs.",
    )
    scheduled_report_check_interval_minutes: int = Field(
        default=15,
        validation_alias=AliasChoices(
            "ANALYTICS_SCHEDULED_REPORT_CHECK_INTERVAL_MINUTES",
            "ANALYTICS__SCHEDULED_REPORT_CHECK_INTERVAL_MINUTES",
        ),
        description="Minutes between scheduled report due-date checks.",
    )
    scheduled_report_max_consecutive_failures: int = Field(
        default=3,
        validation_alias=AliasChoices(
            "ANALYTICS_SCHEDULED_REPORT_MAX_CONSECUTIVE_FAILURES",
            "ANALYTICS__SCHEDULED_REPORT_MAX_CONSECUTIVE_FAILURES",
        ),
        description="Deactivate a schedule after this many consecutive failures.",
    )


class EnrichmentSettings(BaseSettings):
    """External enrichment service configuration.

    Controls passive DNS, ASN lookup, and takedown verification services.

    Env vars: ``I4G_ENRICHMENT__SECURITYTRAILS_API_KEY``, etc.
    """

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    securitytrails_api_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "ENRICHMENT_SECURITYTRAILS_API_KEY",
            "ENRICHMENT__SECURITYTRAILS_API_KEY",
        ),
        description="SecurityTrails API key for passive DNS lookups.",
    )
    takedown_check_interval_hours: int = Field(
        default=12,
        validation_alias=AliasChoices(
            "ENRICHMENT_TAKEDOWN_CHECK_INTERVAL_HOURS",
            "ENRICHMENT__TAKEDOWN_CHECK_INTERVAL_HOURS",
        ),
        description="Hours between takedown verification checks.",
    )
    takedown_max_urls_per_run: int = Field(
        default=200,
        validation_alias=AliasChoices(
            "ENRICHMENT_TAKEDOWN_MAX_URLS_PER_RUN",
            "ENRICHMENT__TAKEDOWN_MAX_URLS_PER_RUN",
        ),
        description="Maximum URLs to check per takedown run.",
    )
    blockchain_vendor: str = Field(
        default="mock",
        validation_alias=AliasChoices(
            "ENRICHMENT_BLOCKCHAIN_VENDOR",
            "ENRICHMENT__BLOCKCHAIN_VENDOR",
        ),
        description="Blockchain analytics vendor: 'chainalysis', 'trm', 'elliptic', or 'mock'.",
    )
    blockchain_api_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "ENRICHMENT_BLOCKCHAIN_API_KEY",
            "ENRICHMENT__BLOCKCHAIN_API_KEY",
        ),
        description="API key for the configured blockchain analytics vendor.",
    )


class PartnerFeedSettings(BaseSettings):
    """Partner indicator feed API configuration.

    Controls the machine-readable, TLP-tagged indicator feed for partner
    organizations. Partners authenticate via API keys separate from
    console auth.

    Env vars: ``I4G_PARTNER_FEED__*``.
    """

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("PARTNER_FEED_ENABLED", "PARTNER_FEED__ENABLED"),
        description="Enable the partner indicator feed API.",
    )
    rate_limit_per_minute: int = Field(
        default=60,
        validation_alias=AliasChoices(
            "PARTNER_FEED_RATE_LIMIT_PER_MINUTE",
            "PARTNER_FEED__RATE_LIMIT_PER_MINUTE",
        ),
        description="Max requests per minute per API key.",
    )
    default_page_size: int = Field(
        default=100,
        validation_alias=AliasChoices(
            "PARTNER_FEED_DEFAULT_PAGE_SIZE",
            "PARTNER_FEED__DEFAULT_PAGE_SIZE",
        ),
        description="Default page size for paginated indicator feed responses.",
    )
    max_page_size: int = Field(
        default=1000,
        validation_alias=AliasChoices(
            "PARTNER_FEED_MAX_PAGE_SIZE",
            "PARTNER_FEED__MAX_PAGE_SIZE",
        ),
        description="Maximum allowed page size for indicator feed requests.",
    )


class FeedbackSettings(BaseSettings):
    """Inline feedback collection via Google Sheets.

    When ``sheet_id`` is empty, the :class:`LoggingFeedbackService` is used
    instead (stdout only).  Set ``enabled = false`` to hide the feedback UI
    and reject API submissions.

    Env vars: ``I4G_FEEDBACK__SHEET_ID``, ``I4G_FEEDBACK__ENABLED``.
    """

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("FEEDBACK_ENABLED", "FEEDBACK__ENABLED"),
        description="Master switch for the feedback feature.",
    )
    sheet_id: str = Field(
        default="",
        validation_alias=AliasChoices("FEEDBACK_SHEET_ID", "FEEDBACK__SHEET_ID"),
        description="Google Sheet spreadsheet ID for feedback storage.",
    )


class EmailSettings(BaseSettings):
    """Email delivery configuration for scheduled reports.

    Set ``provider`` to ``smtp`` and supply SMTP credentials to enable
    real delivery.  The default ``log`` provider writes the email payload
    to the application log only.

    Env vars: ``I4G_EMAIL__PROVIDER``, ``I4G_EMAIL__SMTP_HOST``, etc.
    """

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    provider: str = Field(
        default="log",
        validation_alias=AliasChoices("EMAIL_PROVIDER", "EMAIL__PROVIDER"),
        description="Email provider: 'log' (default) or 'smtp'.",
    )
    smtp_host: str = Field(
        default="localhost",
        validation_alias=AliasChoices("EMAIL_SMTP_HOST", "EMAIL__SMTP_HOST"),
    )
    smtp_port: int = Field(
        default=587,
        validation_alias=AliasChoices("EMAIL_SMTP_PORT", "EMAIL__SMTP_PORT"),
    )
    smtp_user: str = Field(
        default="",
        validation_alias=AliasChoices("EMAIL_SMTP_USER", "EMAIL__SMTP_USER"),
    )
    smtp_password: str = Field(
        default="",
        validation_alias=AliasChoices("EMAIL_SMTP_PASSWORD", "EMAIL__SMTP_PASSWORD"),
    )
    from_address: str = Field(
        default="noreply@i4g.local",
        validation_alias=AliasChoices("EMAIL_FROM_ADDRESS", "EMAIL__FROM_ADDRESS"),
    )
    use_tls: bool = Field(
        default=True,
        validation_alias=AliasChoices("EMAIL_USE_TLS", "EMAIL__USE_TLS"),
    )
