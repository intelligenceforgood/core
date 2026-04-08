"""Configuration loader for i4g services using Pydantic settings."""

from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from i4g.settings.runtime_overrides import apply_environment_overrides, apply_local_defaults, resolve_paths
from i4g.settings.sections import (
    AnalyticsSettings,
    APISettings,
    AutoInvestigateSettings,
    BackfillSettings,
    BigQueryExportSettings,
    CryptoSettings,
    DbAdminSettings,
    DossierJobSettings,
    EmailSettings,
    EnrichmentSettings,
    FeedbackSettings,
    IdentitySettings,
    IngestionSettings,
    IngestRetryJobSettings,
    IntakeJobSettings,
    LLMSettings,
    MlPlatformSettings,
    ObservabilitySettings,
    PartnerFeedSettings,
    RedisSettings,
    ReportSettings,
    RuntimeSettings,
    SearchSettings,
    SecretsSettings,
    SmokeSettings,
    SsiSettings,
    StorageSettings,
    SweepSettings,
    VectorSettings,
)
from i4g.settings.sections._paths import PROJECT_ROOT, detect_project_root

ENV_VAR_NAME = "I4G_ENV"
DEFAULT_ENV = "local"


def _env_project_root(var_name: str) -> Path | None:
    """Resolve an override path from the provided environment variable."""
    raw_value = os.getenv(var_name)
    if not raw_value:
        return None
    return Path(raw_value).expanduser().resolve()


def _detect_project_root() -> Path:
    """Backward-compatible wrapper for project root detection."""
    return detect_project_root()


CONFIG_DIR = PROJECT_ROOT / "config"
DEFAULT_CONFIG_FILE = CONFIG_DIR / "settings.default.toml"
LOCAL_CONFIG_FILE = CONFIG_DIR / "settings.local.toml"
SETTINGS_FILE_ENV_VAR = "I4G_SETTINGS_FILE"


def _resolve_env(explicit_env: str | None = None) -> str:
    """Return the active environment name.

    Args:
        explicit_env: Environment value supplied directly by the caller.

    Returns:
        A stripped environment name, falling back to ``DEFAULT_ENV``.
    """

    env = explicit_env or os.getenv(ENV_VAR_NAME) or DEFAULT_ENV
    return env.strip()


def _env_file_candidates(env: str) -> list[Path]:
    """List candidate ``.env`` files used during settings resolution.

    Args:
        env: Active environment name (for example, ``local`` or ``staging``).

    Returns:
        Ordered list of paths that should be considered when loading
        environment variables from disk.
    """

    return [
        PROJECT_ROOT / ".env",
        PROJECT_ROOT / f".env.{env}",
        PROJECT_ROOT / ".env.local",
    ]


def _resolve_config_path(raw_path: str | None) -> Path | None:
    """Return an absolute config path from user input.

    Args:
        raw_path: The path string to resolve.

    Returns:
        The absolute path if input is provided, otherwise None.
    """
    if not raw_path:
        return None
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = (PROJECT_ROOT / candidate).resolve()
    return candidate


def _config_file_priority(include_missing: bool = False) -> tuple[Path, ...]:
    """Return config files in descending precedence order.

    Args:
        include_missing: If True, include paths even if they don't exist.

    Returns:
        A tuple of config file paths in order of priority.
    """
    ordered: list[Path] = []
    env_override = _resolve_config_path(os.getenv(SETTINGS_FILE_ENV_VAR))
    if env_override:
        ordered.append(env_override)
    ordered.append(LOCAL_CONFIG_FILE)
    ordered.append(DEFAULT_CONFIG_FILE)
    if include_missing:
        return tuple(ordered)
    existing: list[Path] = []
    for path in ordered:
        if path.exists():
            existing.append(path)
    return tuple(existing)


class TomlConfigSettingsSource(PydanticBaseSettingsSource):
    """Pydantic settings source that loads values from a TOML file."""

    def __init__(self, settings_cls: type[BaseSettings], path: Path) -> None:
        super().__init__(settings_cls)
        self.path = path
        self._data: dict[str, Any] | None = None

    def _load(self) -> dict[str, Any]:
        if self._data is not None:
            return self._data
        if not self.path.exists():
            self._data = {}
            return self._data
        try:
            with self.path.open("rb") as handle:
                self._data = tomllib.load(handle)
        except tomllib.TOMLDecodeError as exc:  # pragma: no cover - invalid files surface immediately
            raise ValueError(f"Invalid TOML syntax in {self.path}") from exc
        return self._data

    def __call__(self) -> dict[str, Any]:  # pragma: no cover - trivial wrapper
        return self._load()

    def get_field_value(self, field_name: str, field):  # pragma: no cover - passthrough helper
        data = self._load()
        return data.get(field_name), field_name in data


def _read_env_value(*keys: str) -> str | None:
    """Return the first present environment variable from ``keys``."""

    for key in keys:
        value = os.getenv(key)
        if value is not None:
            return value
    return None


class Settings(BaseSettings):
    """Top-level configuration model with nested sections for each subsystem."""

    env: str = Field(
        default_factory=lambda: _resolve_env(),
        validation_alias=AliasChoices("ENV", "ENVIRONMENT", "RUNTIME__ENV"),
    )
    project_root: Path = Field(
        default=PROJECT_ROOT,
        validation_alias=AliasChoices("PROJECT_ROOT", "RUNTIME__PROJECT_ROOT", "I4G_RUNTIME__PROJECT_ROOT"),
    )
    data_dir: Path = Field(
        default_factory=lambda: PROJECT_ROOT / "data",
        # validation_alias=AliasChoices("DATA_DIR", "RUNTIME__DATA_DIR"),
    )
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)
    api: APISettings = Field(default_factory=APISettings)
    identity: IdentitySettings = Field(default_factory=IdentitySettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    vector: VectorSettings = Field(default_factory=VectorSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    crypto: CryptoSettings = Field(default_factory=CryptoSettings)
    secrets: SecretsSettings = Field(default_factory=SecretsSettings)
    ingestion: IngestionSettings = Field(default_factory=IngestionSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    intake: IntakeJobSettings = Field(default_factory=IntakeJobSettings)
    search: SearchSettings = Field(default_factory=SearchSettings)
    report: ReportSettings = Field(default_factory=ReportSettings)
    ingest_retry_job: IngestRetryJobSettings = Field(default_factory=IngestRetryJobSettings)
    sweep: SweepSettings = Field(default_factory=SweepSettings)
    dossier_job: DossierJobSettings = Field(default_factory=DossierJobSettings)
    smoke: SmokeSettings = Field(default_factory=SmokeSettings)
    ssi: SsiSettings = Field(default_factory=SsiSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    feedback: FeedbackSettings = Field(default_factory=FeedbackSettings)
    analytics: AnalyticsSettings = Field(default_factory=AnalyticsSettings)
    bq_export: BigQueryExportSettings = Field(default_factory=BigQueryExportSettings)
    enrichment: EnrichmentSettings = Field(default_factory=EnrichmentSettings)
    email: EmailSettings = Field(default_factory=EmailSettings)
    partner_feed: PartnerFeedSettings = Field(default_factory=PartnerFeedSettings)
    db_admin: DbAdminSettings = Field(default_factory=DbAdminSettings)
    auto_investigate: AutoInvestigateSettings = Field(default_factory=AutoInvestigateSettings)
    backfill: BackfillSettings = Field(default_factory=BackfillSettings)
    ml: MlPlatformSettings = Field(default_factory=MlPlatformSettings)
    env_files: tuple[Path, ...] = Field(default_factory=tuple, exclude=True)
    config_files: tuple[Path, ...] = Field(default_factory=tuple, exclude=True)

    model_config = SettingsConfigDict(
        env_prefix="I4G_",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        """Extend settings sources with TOML-based config files.

        Priority (Last wins):
        1. Config Files (defaults -> local -> env overrides)
        2. .env files
        3. Environment Variables (I4G_*)
        4. Secrets
        5. Init args
        """

        config_sources = [TomlConfigSettingsSource(settings_cls, path) for path in _config_file_priority()]
        return (
            init_settings,
            file_secret_settings,
            env_settings,
            dotenv_settings,
            *config_sources,
        )

    @model_validator(mode="after")
    def _apply_local_defaults(self) -> Settings:
        """Apply convenience defaults for local development."""
        return apply_local_defaults(self)

    @model_validator(mode="after")
    def _resolve_paths(self) -> Settings:
        """Normalize relative paths once the model is initialised."""
        return resolve_paths(self)

    @model_validator(mode="after")
    def _apply_environment_overrides(self) -> Settings:
        """Force environment-specific defaults after basic resolution."""
        return apply_environment_overrides(self, _read_env_value)

    @property
    def log_level(self) -> str:
        """str: Effective logging level for the running process."""

        return self.runtime.log_level

    @property
    def api_base_url(self) -> str:
        """str: Base URL for API calls (used by scripts and dashboards)."""

        return self.api.base_url

    @property
    def api_key(self) -> str:
        """str: Shared API token for simple authenticated endpoints."""

        return self.api.key

    @property
    def sqlite_path(self) -> Path:
        """Path: Filesystem path for the local SQLite database."""

        return self.storage.sqlite_path

    @property
    def vector_backend(self) -> str:
        """str: Name of the configured vector store backend."""

        return self.vector.backend

    @property
    def vector_collection(self) -> str:
        """str: Default collection or index identifier for vector storage."""

        return self.vector.collection

    @property
    def embedding_model(self) -> str:
        """str: Embedding model identifier used for vector generation."""

        return self.vector.embedding_model

    @property
    def chroma_dir(self) -> Path:
        """Path: Directory where Chroma persists its state."""

        return self.vector.chroma_dir

    @property
    def faiss_dir(self) -> Path:
        """Path: Directory where FAISS index artifacts are stored."""

        return self.vector.faiss_dir

    @property
    def ollama_base_url(self) -> str:
        """str: Base URL for the Ollama HTTP API."""

        return self.llm.ollama_base_url

    @property
    def is_local(self) -> bool:
        """bool: True when the active environment is ``local``."""

        return self.env.lower() == "local"


def _load_settings(env: str | None = None) -> Settings:
    """Load settings with optional environment override.

    Args:
        env: Environment name supplied programmatically.

    Returns:
        Fully parsed :class:`Settings` instance with env files applied.
    """

    resolved_env = _resolve_env(env)
    candidate_files = [path for path in _env_file_candidates(resolved_env) if path.exists()]
    config_files = _config_file_priority()
    return Settings(
        _env_file=[str(path) for path in candidate_files],
        _env_file_encoding="utf-8",
        env=resolved_env,
        env_files=tuple(candidate_files),
        config_files=config_files,
    )


@lru_cache(maxsize=1)
def get_settings(env: str | None = None) -> Settings:
    """Return cached settings for the requested environment."""

    return _load_settings(env)


def reload_settings(env: str | None = None) -> Settings:
    """Clear the cached settings and reload from disk."""

    get_settings.cache_clear()
    return get_settings(env)


__all__ = [
    "Settings",
    "get_settings",
    "reload_settings",
    "PROJECT_ROOT",
    "ENV_VAR_NAME",
]
