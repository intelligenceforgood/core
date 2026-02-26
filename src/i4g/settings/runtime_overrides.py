"""Runtime validators and environment override helpers for Settings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING
from collections.abc import Callable

if TYPE_CHECKING:
    from i4g.settings.config import Settings


def apply_local_defaults(settings: Settings) -> Settings:
    """Apply convenience defaults for local development."""
    if settings.env == "local" and not settings.pii.pepper:
        update = {"pepper": "local-secret-pepper"}
        object.__setattr__(settings, "pii", settings.pii.model_copy(update=update))
    return settings


def resolve_paths(settings: Settings) -> Settings:
    """Normalize relative paths once the model is initialised."""
    if not settings.data_dir.is_absolute():
        object.__setattr__(settings, "data_dir", (settings.project_root / settings.data_dir).resolve())

    storage_updates: dict[str, object] = {}
    if not settings.storage.sqlite_path.is_absolute():
        storage_updates["sqlite_path"] = (settings.project_root / settings.storage.sqlite_path).resolve()
    if not settings.storage.evidence_local_dir.is_absolute():
        storage_updates["evidence_local_dir"] = (settings.project_root / settings.storage.evidence_local_dir).resolve()
    if storage_updates:
        object.__setattr__(settings, "storage", settings.storage.model_copy(update=storage_updates))

    vector_updates: dict[str, object] = {}
    if not settings.vector.chroma_dir.is_absolute():
        vector_updates["chroma_dir"] = (settings.project_root / settings.vector.chroma_dir).resolve()
    if not settings.vector.faiss_dir.is_absolute():
        vector_updates["faiss_dir"] = (settings.project_root / settings.vector.faiss_dir).resolve()
    if vector_updates:
        object.__setattr__(settings, "vector", settings.vector.model_copy(update=vector_updates))

    if settings.secrets.local_env_file and not settings.secrets.local_env_file.is_absolute():
        secrets_update = {"local_env_file": (settings.project_root / settings.secrets.local_env_file).resolve()}
        object.__setattr__(settings, "secrets", settings.secrets.model_copy(update=secrets_update))

    normalize_ingestion_paths(settings)

    # SSI playbook directory
    pb_dir = Path(settings.ssi_job.playbook_dir)
    if not pb_dir.is_absolute():
        ssi_update = {"playbook_dir": str((settings.project_root / pb_dir).resolve())}
        object.__setattr__(settings, "ssi_job", settings.ssi_job.model_copy(update=ssi_update))

    return settings


def normalize_ingestion_paths(settings: Settings) -> None:
    """Ensure ingestion paths resolve relative to the project root.

    GCS URIs (``gs://…``) are left untouched — they are not local paths.
    """
    dataset_path = settings.ingestion.dataset_path

    # GCS URIs must not be coerced into Path objects.
    if isinstance(dataset_path, str) and dataset_path.startswith("gs://"):
        return

    normalized = dataset_path
    if dataset_path and not isinstance(dataset_path, Path):
        normalized = Path(dataset_path)
    if normalized and not normalized.is_absolute():
        normalized = (settings.project_root / normalized).resolve()
    if normalized and normalized != dataset_path:
        object.__setattr__(settings, "ingestion", settings.ingestion.model_copy(update={"dataset_path": normalized}))


def apply_environment_overrides(
    settings: Settings,
    read_env_value: Callable[..., str | None],
) -> Settings:
    """Force environment-specific defaults and legacy env-alias overrides."""
    env_name = settings.env.lower()

    if env_name == "local":
        identity_update = {
            "provider": "mock",
            "disable_auth": True,
            "audience": None,
            "issuer": None,
            "client_id": None,
        }
        object.__setattr__(settings, "identity", settings.identity.model_copy(update=identity_update))

        storage_update = {
            "structured_backend": "sqlite",
            "cloudsql_instance": None,
            "cloudsql_database": None,
            "evidence_bucket": None,
            "report_bucket": None,
        }
        object.__setattr__(settings, "storage", settings.storage.model_copy(update=storage_update))

        vector_update = {
            "backend": "chroma",
            "collection": settings.vector.collection or "i4g_vectors",
            "pgvector_dsn": None,
            "vertex_ai_index": None,
            "vertex_ai_project": None,
        }
        object.__setattr__(settings, "vector", settings.vector.model_copy(update=vector_update))

        llm_update = {
            "provider": "ollama",
            "vertex_ai_model": None,
            "vertex_ai_project": None,
        }
        object.__setattr__(settings, "llm", settings.llm.model_copy(update=llm_update))

        secrets_update = {"use_secret_manager": False, "project": None}
        if not settings.secrets.local_env_file:
            secrets_update["local_env_file"] = settings.project_root / ".env.local"
        object.__setattr__(settings, "secrets", settings.secrets.model_copy(update=secrets_update))

        pii_update = {
            "require_pepper": False,
            "pepper": settings.pii.pepper or "local-dev-pepper",
        }
        object.__setattr__(settings, "pii", settings.pii.model_copy(update=pii_update))

        ingestion_update = {
            "enable_scheduled_jobs": False,
            "scheduler_project": None,
            "default_service_account": None,
        }
        object.__setattr__(settings, "ingestion", settings.ingestion.model_copy(update=ingestion_update))

        observability_update = {"structured_logging": False, "otlp_endpoint": None}
        object.__setattr__(settings, "observability", settings.observability.model_copy(update=observability_update))

    ingestion_alias_updates: dict[str, object] = {}

    def _legacy_env_keys(*keys: str) -> tuple[str, ...]:
        resolved: list[str] = []
        seen: set[str] = set()
        for key in keys:
            for candidate in (f"I4G_{key}", key):
                if candidate in seen:
                    continue
                seen.add(candidate)
                resolved.append(candidate)
        return tuple(resolved)

    def _ingestion_bool(field: str, *keys: str) -> None:
        value = read_env_value(*_legacy_env_keys(*keys))
        if value is None:
            return
        ingestion_alias_updates[field] = value.strip().lower() not in {"false", "0", "off", "no"}

    def _ingestion_str(field: str, *keys: str) -> None:
        value = read_env_value(*_legacy_env_keys(*keys))
        if value is None:
            return
        ingestion_alias_updates[field] = value.strip()

    def _ingestion_int(field: str, *keys: str) -> None:
        value = read_env_value(*_legacy_env_keys(*keys))
        if value is None:
            return
        try:
            ingestion_alias_updates[field] = int(value.strip())
        except ValueError:
            pass

    _ingestion_bool("enable_scheduled_jobs", "INGESTION__ENABLE_SCHEDULED_JOBS", "INGESTION_ENABLE_SCHEDULED_JOBS", "INGEST__ENABLE_SCHEDULED_JOBS", "INGEST_ENABLE_SCHEDULED_JOBS")
    _ingestion_bool("enable_sql", "INGESTION__ENABLE_SQL", "INGESTION_ENABLE_SQL", "INGEST__ENABLE_SQL", "INGEST_ENABLE_SQL")
    _ingestion_bool("enable_vertex", "INGESTION__ENABLE_VERTEX", "INGESTION_ENABLE_VERTEX", "INGEST__ENABLE_VERTEX", "INGEST_ENABLE_VERTEX")
    _ingestion_bool("enable_vector_store", "INGESTION__ENABLE_VECTOR_STORE", "INGESTION_ENABLE_VECTOR_STORE", "INGESTION__ENABLE_VECTOR", "INGESTION_ENABLE_VECTOR", "INGEST__ENABLE_VECTOR_STORE", "INGEST_ENABLE_VECTOR_STORE", "INGEST__ENABLE_VECTOR", "INGEST_ENABLE_VECTOR")
    _ingestion_str("default_region", "INGESTION__DEFAULT_REGION", "INGESTION_DEFAULT_REGION", "INGEST__DEFAULT_REGION", "INGEST_DEFAULT_REGION")
    _ingestion_str("scheduler_project", "INGESTION__SCHEDULER_PROJECT", "INGESTION_SCHEDULER_PROJECT", "INGEST__SCHEDULER_PROJECT", "INGEST_SCHEDULER_PROJECT")
    _ingestion_str("default_service_account", "INGESTION__SERVICE_ACCOUNT", "INGESTION_SERVICE_ACCOUNT", "INGEST__SERVICE_ACCOUNT", "INGEST_SERVICE_ACCOUNT")
    _ingestion_str("default_dataset", "INGESTION__DEFAULT_DATASET", "INGESTION_DEFAULT_DATASET", "INGEST__DEFAULT_DATASET", "INGEST_DEFAULT_DATASET")
    _ingestion_str("dataset_path", "INGESTION__JSONL_PATH", "INGESTION_JSONL_PATH", "INGEST__JSONL_PATH", "INGEST_JSONL_PATH")
    _ingestion_int("fanout_timeout_seconds", "INGESTION__FANOUT_TIMEOUT_SECONDS", "INGESTION_FANOUT_TIMEOUT_SECONDS", "INGEST__FANOUT_TIMEOUT_SECONDS", "INGEST_FANOUT_TIMEOUT_SECONDS")
    _ingestion_int("batch_limit", "INGESTION__BATCH_LIMIT", "INGESTION_BATCH_LIMIT", "INGEST__BATCH_LIMIT", "INGEST_BATCH_LIMIT")
    _ingestion_int("max_retries", "INGESTION__MAX_RETRIES", "INGESTION_MAX_RETRIES", "INGEST__MAX_RETRIES", "INGEST_MAX_RETRIES")
    _ingestion_int("retry_delay_seconds", "INGESTION__RETRY_DELAY_SECONDS", "INGESTION_RETRY_DELAY_SECONDS", "INGEST__RETRY_DELAY_SECONDS", "INGEST_RETRY_DELAY_SECONDS")
    _ingestion_bool("dry_run", "INGESTION__DRY_RUN", "INGESTION_DRY_RUN", "INGEST__DRY_RUN", "INGEST_DRY_RUN")
    _ingestion_bool("reset_vector", "INGESTION__RESET_VECTOR", "INGESTION_RESET_VECTOR", "INGEST__RESET_VECTOR", "INGEST_RESET_VECTOR")

    if ingestion_alias_updates:
        object.__setattr__(settings, "ingestion", settings.ingestion.model_copy(update=ingestion_alias_updates))
        normalize_ingestion_paths(settings)

    provider_override = read_env_value("I4G_LLM__PROVIDER", "I4G_LLM_PROVIDER", "LLM__PROVIDER", "LLM_PROVIDER")
    if provider_override:
        llm_updates = {"provider": provider_override.strip().lower()}
        object.__setattr__(settings, "llm", settings.llm.model_copy(update=llm_updates))

    account_list_updates: dict[str, object] = {}
    header_override = read_env_value(
        "I4G_ACCOUNT_LIST__HEADER_NAME",
        "I4G_ACCOUNT_LIST_HEADER_NAME",
        "ACCOUNT_LIST__HEADER_NAME",
        "ACCOUNT_LIST_HEADER_NAME",
    )
    if header_override:
        account_list_updates["header_name"] = header_override.strip()

    require_override = read_env_value(
        "I4G_ACCOUNT_LIST__REQUIRE_API_KEY",
        "I4G_ACCOUNT_LIST_REQUIRE_API_KEY",
        "ACCOUNT_LIST__REQUIRE_API_KEY",
        "ACCOUNT_LIST_REQUIRE_API_KEY",
    )
    if require_override is not None:
        account_list_updates["require_api_key"] = require_override.strip().lower() not in {"false", "0", "off", "no"}

    formats_override = read_env_value(
        "I4G_ACCOUNT_LIST__DEFAULT_FORMATS",
        "I4G_ACCOUNT_LIST_DEFAULT_FORMATS",
        "ACCOUNT_LIST__DEFAULT_FORMATS",
        "ACCOUNT_LIST_DEFAULT_FORMATS",
    )
    if formats_override:
        parsed_formats: list[str] = []
        try:
            candidate = json.loads(formats_override)
            if isinstance(candidate, list):
                parsed_formats = [str(item).strip() for item in candidate if str(item).strip()]
        except json.JSONDecodeError:
            pass
        if not parsed_formats:
            parsed_formats = [chunk.strip() for chunk in formats_override.split(",") if chunk.strip()]
        account_list_updates["default_formats"] = parsed_formats

    if account_list_updates:
        object.__setattr__(settings, "account_list", settings.account_list.model_copy(update=account_list_updates))

    return settings
