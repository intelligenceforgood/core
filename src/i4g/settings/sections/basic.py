"""Core runtime/API/storage section models."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from i4g.settings.sections._paths import PROJECT_ROOT


class RuntimeSettings(BaseSettings):
    """Process-level runtime controls."""

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    log_level: str = Field(
        default="INFO",
        validation_alias=AliasChoices("LOG_LEVEL", "RUNTIME__LOG_LEVEL"),
    )
    fallback_dir: Path = Field(
        default=Path("/tmp/i4g/evidence"),
        validation_alias=AliasChoices("RUNTIME_FALLBACK_DIR", "RUNTIME__FALLBACK_DIR"),
        description="Fallback directory for local evidence storage when primary path is not writable.",
    )


class APISettings(BaseSettings):
    """API endpoint configuration shared by CLI + dashboards."""

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    base_url: str = Field(
        default="http://127.0.0.1:8000",
        validation_alias=AliasChoices("API_URL", "API__BASE_URL"),
    )
    key: str = Field(
        default="dev-analyst-token",
        validation_alias=AliasChoices("API_KEY", "API__KEY"),
    )
    rate_limit_per_minute: int = Field(
        default=60,
        validation_alias=AliasChoices("API_RATE_LIMIT", "API__RATE_LIMIT_PER_MINUTE"),
    )
    cors_origins: list[str] = Field(
        default=["*"],
        validation_alias=AliasChoices("API_CORS_ORIGINS", "API__CORS_ORIGINS"),
        description="Allowed CORS origins. Defaults to ['*'] for local dev; override in cloud envs.",
    )
    partner_mode: bool = Field(
        default=False,
        validation_alias=AliasChoices("PARTNER_MODE", "API__PARTNER_MODE"),
        description="Master switch to run API in partner mode (only exposing partner routes).",
    )


class IdentitySettings(BaseSettings):
    """Identity provider wiring for auth-enabled services."""

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    provider: Literal["mock", "google_identity", "authentik", "firebase"] = Field(
        default="mock",
        validation_alias=AliasChoices("IDENTITY_PROVIDER", "IDENTITY__PROVIDER"),
    )
    audience: str | None = Field(
        default=None,
        validation_alias=AliasChoices("IDENTITY_AUDIENCE", "IDENTITY__AUDIENCE"),
    )
    issuer: str | None = Field(
        default=None,
        validation_alias=AliasChoices("IDENTITY_ISSUER", "IDENTITY__ISSUER"),
    )
    client_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("IDENTITY_CLIENT_ID", "IDENTITY__CLIENT_ID"),
    )
    iap_backend_audience: str | None = Field(
        default=None,
        validation_alias=AliasChoices("IDENTITY_IAP_BACKEND_AUDIENCE", "IDENTITY__IAP_BACKEND_AUDIENCE"),
        description=(
            "IAP backend-service audience string "
            "(/projects/PROJECT_NUMBER/global/backendServices/BACKEND_ID). "
            "Used to verify X-Goog-IAP-JWT-Assertion tokens whose audience "
            "differs from the OAuth client ID."
        ),
    )
    disable_auth: bool = Field(
        default=False,
        validation_alias=AliasChoices("IDENTITY_DISABLE_AUTH", "IDENTITY__DISABLE_AUTH"),
    )


class StorageSettings(BaseSettings):
    """Structured + blob storage configuration."""

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    structured_backend: Literal["sqlite", "cloudsql"] = Field(
        default="sqlite",
        validation_alias=AliasChoices("STRUCTURED_BACKEND", "STORAGE__STRUCTURED_BACKEND"),
    )
    sqlite_path: Path = Field(
        default=PROJECT_ROOT / "data" / "i4g_store.db",
    )
    evidence_bucket: str | None = Field(
        default=None,
        validation_alias=AliasChoices("STORAGE_EVIDENCE_BUCKET", "STORAGE__EVIDENCE_BUCKET"),
    )
    evidence_local_dir: Path = Field(
        default=PROJECT_ROOT / "data" / "evidence",
        validation_alias=AliasChoices("STORAGE_EVIDENCE_LOCAL_DIR", "STORAGE__EVIDENCE__LOCAL_DIR"),
    )
    ssi_evidence_bucket: str | None = Field(
        default=None,
        description="GCS bucket for SSI investigation evidence artifacts.",
        validation_alias=AliasChoices("STORAGE__SSI_EVIDENCE_BUCKET", "STORAGE_SSI_EVIDENCE_BUCKET"),
    )
    ssi_evidence_prefix: str = Field(
        default="investigations",
        description="Key prefix inside the SSI evidence bucket.",
        validation_alias=AliasChoices("STORAGE__SSI_EVIDENCE_PREFIX", "STORAGE_SSI_EVIDENCE_PREFIX"),
    )
    report_bucket: str | None = Field(
        default=None,
        validation_alias=AliasChoices("STORAGE_REPORT_BUCKET", "STORAGE__REPORT_BUCKET", "I4G_STORAGE__REPORT_BUCKET"),
    )
    cloudsql_instance: str | None = Field(
        default=None,
        validation_alias=AliasChoices("APP__CLOUDSQL__INSTANCE", "I4G_APP__CLOUDSQL__INSTANCE"),
    )
    cloudsql_database: str | None = Field(
        default=None,
        validation_alias=AliasChoices("APP__CLOUDSQL__DATABASE", "I4G_APP__CLOUDSQL__DATABASE"),
    )
    cloudsql_user: str | None = Field(
        default=None,
        validation_alias=AliasChoices("APP__CLOUDSQL__USER", "I4G_APP__CLOUDSQL__USER"),
    )
    cloudsql_password: str | None = Field(
        default=None,
        validation_alias=AliasChoices("APP__CLOUDSQL__PASSWORD", "I4G_APP__CLOUDSQL__PASSWORD"),
    )
    cloudsql_enable_iam_auth: bool = Field(
        default=False,
        validation_alias=AliasChoices("APP__CLOUDSQL__ENABLE_IAM_AUTH", "I4G_APP__CLOUDSQL__ENABLE_IAM_AUTH"),
    )
    retention_enabled: bool = Field(
        default=True,
        description="Master switch for automated retention purge. Set I4G_STORAGE__RETENTION_ENABLED=false to disable.",
        validation_alias=AliasChoices("STORAGE__RETENTION_ENABLED", "STORAGE_RETENTION_ENABLED"),
    )
    retention_days: int = Field(
        default=90,
        description="Number of days after resolution before automated purge. Set via I4G_STORAGE__RETENTION_DAYS.",
        validation_alias=AliasChoices("STORAGE__RETENTION_DAYS", "STORAGE_RETENTION_DAYS"),
    )
    retention_grace_days: int = Field(
        default=30,
        description="Days after soft-delete before hard purge. Set via I4G_STORAGE__RETENTION_GRACE_DAYS.",
        validation_alias=AliasChoices("STORAGE__RETENTION_GRACE_DAYS", "STORAGE_RETENTION_GRACE_DAYS"),
    )


class DbAdminSettings(BaseSettings):
    """Postgres admin credentials for running Alembic migrations via cloud-sql-proxy."""

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    dev_password: str | None = Field(
        default=None,
        description="Postgres password for i4g-dev-db.",
        validation_alias=AliasChoices("DB_ADMIN__DEV_PASSWORD", "I4G_DB_ADMIN__DEV_PASSWORD"),
    )
    prod_password: str | None = Field(
        default=None,
        description="Postgres password for i4g-prod-db.",
        validation_alias=AliasChoices("DB_ADMIN__PROD_PASSWORD", "I4G_DB_ADMIN__PROD_PASSWORD"),
    )
