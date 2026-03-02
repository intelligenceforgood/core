"""Unit tests covering environment variable overrides for settings."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from i4g.settings.config import PROJECT_ROOT, reload_settings


@pytest.fixture(autouse=True)
def isolate_settings_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Prevent developer-local config files from altering defaults."""

    monkeypatch.delenv("I4G_SETTINGS_FILE", raising=False)
    monkeypatch.setattr("i4g.settings.config.LOCAL_CONFIG_FILE", tmp_path / "settings.local.toml")


def _clear_env(monkeypatch: object, *names: str) -> None:
    """Remove env vars for every alias and prefixed variant."""

    for name in names:
        monkeypatch.delenv(name, raising=False)
        if name.startswith("I4G_"):
            monkeypatch.delenv(name.removeprefix("I4G_"), raising=False)
        else:
            monkeypatch.delenv(f"I4G_{name}", raising=False)


def _set_env(monkeypatch: object, name: str, value: str) -> None:
    """Set both prefixed and unprefixed aliases for reliability."""

    monkeypatch.setenv(name, value)


def test_search_weight_bounds(monkeypatch: object) -> None:
    """Semantic/structured weights must remain within 0–1 inclusive."""

    _clear_env(
        monkeypatch,
        "I4G_SEARCH__SEMANTIC_WEIGHT",
        "I4G_SEARCH__STRUCTURED_WEIGHT",
        "SEARCH_SEMANTIC_WEIGHT",
        "SEARCH_STRUCTURED_WEIGHT",
    )
    _set_env(monkeypatch, "I4G_SEARCH__SEMANTIC_WEIGHT", "-0.1")

    with pytest.raises(ValidationError):
        reload_settings(env="dev")


def test_search_weights_not_both_zero(monkeypatch: object) -> None:
    """At least one hybrid search weight must remain positive."""

    _clear_env(
        monkeypatch,
        "I4G_SEARCH__SEMANTIC_WEIGHT",
        "I4G_SEARCH__STRUCTURED_WEIGHT",
        "SEARCH_SEMANTIC_WEIGHT",
        "SEARCH_STRUCTURED_WEIGHT",
    )
    _set_env(monkeypatch, "I4G_SEARCH__SEMANTIC_WEIGHT", "0")
    _set_env(monkeypatch, "I4G_SEARCH__STRUCTURED_WEIGHT", "0")

    with pytest.raises(ValidationError):
        reload_settings(env="dev")


def test_search_schema_entity_example_limit_override(monkeypatch: object) -> None:
    """Schema entity example limits should follow env overrides."""

    _clear_env(
        monkeypatch,
        "I4G_SEARCH__SCHEMA_ENTITY_EXAMPLE_LIMIT",
        "SEARCH_SCHEMA_ENTITY_EXAMPLE_LIMIT",
        "SEARCH__SCHEMA_ENTITY_EXAMPLE_LIMIT",
    )

    default_settings = reload_settings(env="dev")
    assert default_settings.search.schema_entity_example_limit == 5

    _set_env(monkeypatch, "I4G_SEARCH__SCHEMA_ENTITY_EXAMPLE_LIMIT", "3")
    overridden = reload_settings(env="dev")
    assert overridden.search.schema_entity_example_limit == 3


def test_saved_search_settings_env_override(monkeypatch: object) -> None:
    """Saved-search migration defaults must follow settings/env overrides."""

    _clear_env(
        monkeypatch,
        "I4G_SEARCH__SAVED_SEARCH__MIGRATION_TAG",
        "I4G_SEARCH__SAVED_SEARCH__SCHEMA_VERSION",
        "SEARCH_SAVED_SEARCH_MIGRATION_TAG",
        "SEARCH_SAVED_SEARCH_SCHEMA_VERSION",
    )

    defaults = reload_settings(env="dev")
    assert defaults.search.saved_search.migration_tag == "hybrid-v1"
    assert defaults.search.saved_search.schema_version == ""

    _set_env(monkeypatch, "I4G_SEARCH__SAVED_SEARCH__MIGRATION_TAG", "hybrid-v2")
    _set_env(monkeypatch, "I4G_SEARCH__SAVED_SEARCH__SCHEMA_VERSION", "schema-v3")

    overridden = reload_settings(env="dev")
    assert overridden.search.saved_search.migration_tag == "hybrid-v2"
    assert overridden.search.saved_search.schema_version == "schema-v3"


def test_llm_provider_env_override(monkeypatch: object) -> None:
    """Ensure the llm.provider value follows environment overrides."""

    _clear_env(monkeypatch, "I4G_LLM__PROVIDER", "I4G_LLM_PROVIDER", "LLM__PROVIDER", "LLM_PROVIDER")

    default_settings = reload_settings(env="dev")
    assert default_settings.llm.provider == "ollama"

    _set_env(monkeypatch, "I4G_LLM__PROVIDER", "mock")
    overridden_settings = reload_settings(env="dev")
    assert overridden_settings.llm.provider == "mock"


def test_account_list_env_overrides(monkeypatch: object) -> None:
    """Verify account list settings respect header/require_api_key/default format env vars."""

    _clear_env(
        monkeypatch,
        "I4G_ACCOUNT_LIST__HEADER_NAME",
        "I4G_ACCOUNT_LIST_HEADER_NAME",
        "ACCOUNT_LIST__HEADER_NAME",
        "ACCOUNT_LIST_HEADER_NAME",
        "I4G_ACCOUNT_LIST__REQUIRE_API_KEY",
        "I4G_ACCOUNT_LIST_REQUIRE_API_KEY",
        "ACCOUNT_LIST__REQUIRE_API_KEY",
        "ACCOUNT_LIST_REQUIRE_API_KEY",
        "I4G_ACCOUNT_LIST__DEFAULT_FORMATS",
        "I4G_ACCOUNT_LIST_DEFAULT_FORMATS",
        "ACCOUNT_LIST__DEFAULT_FORMATS",
        "ACCOUNT_LIST_DEFAULT_FORMATS",
    )

    default_settings = reload_settings(env="dev")
    assert default_settings.account_list.header_name == "X-ACCOUNTLIST-KEY"
    assert default_settings.account_list.require_api_key is True
    assert default_settings.account_list.default_formats == []

    _set_env(monkeypatch, "I4G_ACCOUNT_LIST__HEADER_NAME", "X-ACCOUNT-LIST-OVERRIDE")
    _set_env(monkeypatch, "I4G_ACCOUNT_LIST__REQUIRE_API_KEY", "false")
    _set_env(monkeypatch, "I4G_ACCOUNT_LIST__DEFAULT_FORMATS", json.dumps(["pdf", "xlsx"]))

    overridden_settings = reload_settings(env="dev")
    assert overridden_settings.account_list.header_name == "X-ACCOUNT-LIST-OVERRIDE"
    assert overridden_settings.account_list.require_api_key is False
    assert overridden_settings.account_list.default_formats == ["pdf", "xlsx"]


def test_ingestion_sql_toggle_env_overrides(monkeypatch: object) -> None:
    """Ensure ingestion fan-out toggles respect environment overrides."""

    _clear_env(
        monkeypatch,
        "I4G_INGEST__ENABLE_SQL",
        "I4G_INGEST__ENABLE_VERTEX",
        "I4G_INGEST__DEFAULT_DATASET",
        "I4G_INGEST__MAX_RETRIES",
        "I4G_INGEST__RETRY_DELAY_SECONDS",
        "I4G_INGESTION__RETRY_DELAY_SECONDS",
    )

    default_settings = reload_settings(env="dev")
    assert default_settings.ingestion.enable_sql is True
    assert default_settings.ingestion.enable_vertex is False
    assert default_settings.ingestion.enable_vector_store is True
    assert default_settings.ingestion.default_dataset == "unknown"
    assert default_settings.ingestion.max_retries == 3
    assert default_settings.ingestion.retry_delay_seconds == 60

    _set_env(monkeypatch, "I4G_INGEST__ENABLE_SQL", "false")
    _set_env(monkeypatch, "I4G_INGEST__ENABLE_VERTEX", "true")
    _set_env(monkeypatch, "I4G_INGEST__DEFAULT_DATASET", "account_list")
    _set_env(monkeypatch, "I4G_INGEST__MAX_RETRIES", "5")
    _set_env(monkeypatch, "I4G_INGEST__ENABLE_VECTOR", "false")
    _set_env(monkeypatch, "I4G_INGESTION__RETRY_DELAY_SECONDS", "120")

    overridden = reload_settings(env="dev")
    assert overridden.ingestion.enable_sql is False
    assert overridden.ingestion.enable_vertex is True
    assert overridden.ingestion.enable_vector_store is False
    assert overridden.ingestion.default_dataset == "account_list"
    assert overridden.ingestion.max_retries == 5
    assert overridden.ingestion.retry_delay_seconds == 120


def test_settings_file_override(tmp_path, monkeypatch: object) -> None:
    """Ensure TOML config files populate settings without manual env vars."""

    _clear_env(
        monkeypatch,
        "I4G_INGEST__DEFAULT_DATASET",
        "I4G_ENV",
    )
    _set_env(monkeypatch, "I4G_ENV", "dev")

    settings_file = tmp_path / "settings.local.toml"
    settings_file.write_text(
        textwrap.dedent(
            """
            env = "dev"

            [ingestion]
            default_dataset = "toml_dataset"
            """
        ).strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("I4G_SETTINGS_FILE", str(settings_file))
    settings_from_file = reload_settings()
    assert settings_from_file.ingestion.default_dataset == "toml_dataset"
    assert settings_file in settings_from_file.config_files

    _set_env(monkeypatch, "I4G_INGEST__DEFAULT_DATASET", "env_dataset")
    env_override = reload_settings()
    assert env_override.ingestion.default_dataset == "env_dataset"


def test_tokenization_env_overrides(monkeypatch: object) -> None:
    """Tokenization settings should honor pepper and requirement flags."""

    _clear_env(
        monkeypatch,
        "I4G_PII__PEPPER",
        "PII_PEPPER",
        "I4G_TOKENIZATION__PEPPER",
        "TOKENIZATION_PEPPER",
        "I4G_PII__REQUIRE_PEPPER",
        "PII_REQUIRE_PEPPER",
        "I4G_TOKENIZATION__REQUIRE_PEPPER",
        "TOKENIZATION_REQUIRE_PEPPER",
        "I4G_PII__PEPPER_VERSION",
        "PII_PEPPER_VERSION",
        "I4G_TOKENIZATION__PEPPER_VERSION",
        "TOKENIZATION_PEPPER_VERSION",
    )

    defaults = reload_settings(env="dev")
    assert defaults.pii.pepper_version == "v1"
    assert defaults.pii.require_pepper is True

    # Test with new PII prefix
    _set_env(monkeypatch, "I4G_PII__PEPPER", "test-pepper")
    _set_env(monkeypatch, "I4G_PII__PEPPER_VERSION", "v2")
    _set_env(monkeypatch, "I4G_PII__REQUIRE_PEPPER", "false")

    overridden = reload_settings(env="dev")
    assert overridden.pii.pepper == "test-pepper"
    assert overridden.pii.pepper_version == "v2"
    assert overridden.pii.require_pepper is False


def test_ingestion_local_config_dataset_override(tmp_path, monkeypatch: object) -> None:
    """Local config files should override the ingestion default dataset."""

    _clear_env(monkeypatch, "I4G_INGEST__DEFAULT_DATASET", "I4G_SETTINGS_FILE", "I4G_ENV")

    local_file = tmp_path / "settings.local.toml"
    local_file.write_text(
        textwrap.dedent(
            """
            env = "dev"

            [ingestion]
            default_dataset = "local_dataset"
            """
        ).strip(),
        encoding="utf-8",
    )

    default_file = tmp_path / "settings.default.toml"
    default_file.write_text('env = "dev"', encoding="utf-8")

    monkeypatch.setattr("i4g.settings.config.LOCAL_CONFIG_FILE", local_file)
    monkeypatch.setattr("i4g.settings.config.DEFAULT_CONFIG_FILE", default_file)

    settings_from_local = reload_settings(env="dev")
    assert settings_from_local.ingestion.default_dataset == "local_dataset"
    assert local_file in settings_from_local.config_files
    assert default_file in settings_from_local.config_files


def test_ingestion_default_config_dataset_override(tmp_path, monkeypatch: object) -> None:
    """Default config files should populate ingestion dataset when local overrides are absent."""

    _clear_env(monkeypatch, "I4G_INGEST__DEFAULT_DATASET", "I4G_SETTINGS_FILE", "I4G_ENV")

    default_file = tmp_path / "settings.default.toml"
    default_file.write_text(
        textwrap.dedent(
            """
            env = "dev"

            [ingestion]
            default_dataset = "baseline_dataset"
            """
        ).strip(),
        encoding="utf-8",
    )

    missing_local_file = tmp_path / "settings.local.toml"

    monkeypatch.setattr("i4g.settings.config.LOCAL_CONFIG_FILE", missing_local_file)
    monkeypatch.setattr("i4g.settings.config.DEFAULT_CONFIG_FILE", default_file)

    settings_from_default = reload_settings(env="dev")
    assert settings_from_default.ingestion.default_dataset == "baseline_dataset"
    assert default_file in settings_from_default.config_files
    assert missing_local_file not in settings_from_default.config_files


def test_ingestion_dataset_path_from_config(tmp_path, monkeypatch: object) -> None:
    """Relative dataset paths in config files should resolve against the project root."""

    _clear_env(monkeypatch, "I4G_INGEST__JSONL_PATH", "I4G_SETTINGS_FILE", "I4G_ENV")

    local_file = tmp_path / "settings.local.toml"
    local_file.write_text(
        textwrap.dedent(
            """
            env = "dev"

            [ingestion]
            dataset_path = "data/manual_demo/network_entities.jsonl"
            """
        ).strip(),
        encoding="utf-8",
    )

    default_file = tmp_path / "settings.default.toml"
    default_file.write_text('env = "dev"', encoding="utf-8")

    monkeypatch.setattr("i4g.settings.config.LOCAL_CONFIG_FILE", local_file)
    monkeypatch.setattr("i4g.settings.config.DEFAULT_CONFIG_FILE", default_file)

    settings_with_path = reload_settings(env="dev")
    expected = (PROJECT_ROOT / "data/manual_demo/network_entities.jsonl").resolve()
    assert settings_with_path.ingestion.dataset_path == expected


def test_ingestion_dataset_path_env_override(monkeypatch: object) -> None:
    """Environment variables still override dataset paths when provided."""

    _clear_env(monkeypatch, "I4G_INGEST__JSONL_PATH", "I4G_SETTINGS_FILE", "I4G_ENV")
    temp_path = Path("/tmp/override.jsonl")
    monkeypatch.setenv("I4G_INGEST__JSONL_PATH", str(temp_path))
    settings_override = reload_settings(env="dev")
    assert settings_override.ingestion.dataset_path == temp_path


def test_ingestion_batch_limit_from_config(tmp_path, monkeypatch: object) -> None:
    """Batch limits configured via TOML files should populate settings."""

    _clear_env(monkeypatch, "I4G_INGEST__BATCH_LIMIT", "I4G_SETTINGS_FILE", "I4G_ENV")

    local_file = tmp_path / "settings.local.toml"
    local_file.write_text(
        textwrap.dedent(
            """
            env = "dev"

            [ingestion]
            batch_limit = 25
            """
        ).strip(),
        encoding="utf-8",
    )
    default_file = tmp_path / "settings.default.toml"
    default_file.write_text('env = "dev"', encoding="utf-8")

    monkeypatch.setattr("i4g.settings.config.LOCAL_CONFIG_FILE", local_file)
    monkeypatch.setattr("i4g.settings.config.DEFAULT_CONFIG_FILE", default_file)

    settings_with_batch = reload_settings(env="dev")
    assert settings_with_batch.ingestion.batch_limit == 25


def test_ingestion_batch_limit_env_override(monkeypatch: object) -> None:
    """Environment variables override batch_limit settings values."""

    _clear_env(monkeypatch, "I4G_INGEST__BATCH_LIMIT", "I4G_SETTINGS_FILE", "I4G_ENV")
    monkeypatch.setenv("I4G_INGEST__BATCH_LIMIT", "7")
    settings_override = reload_settings(env="dev")
    assert settings_override.ingestion.batch_limit == 7


def test_observability_statsd_env_overrides(monkeypatch: object) -> None:
    """Verify StatsD-related observability settings honor env overrides."""

    _clear_env(
        monkeypatch,
        "I4G_OBSERVABILITY__STATSD_HOST",
        "OBSERVABILITY__STATSD_HOST",
        "OBS_STATSD_HOST",
        "I4G_OBSERVABILITY__STATSD_PORT",
        "OBS_STATSD_PORT",
        "OBSERVABILITY__STATSD_PORT",
        "I4G_OBSERVABILITY__STATSD_PREFIX",
        "OBS_STATSD_PREFIX",
        "OBSERVABILITY__STATSD_PREFIX",
        "I4G_OBSERVABILITY__SERVICE_NAME",
        "OBS_SERVICE_NAME",
        "OBSERVABILITY__SERVICE_NAME",
    )

    default_settings = reload_settings(env="dev")
    assert default_settings.observability.statsd_host is None
    assert default_settings.observability.statsd_port == 8125
    assert default_settings.observability.statsd_prefix == "i4g"
    assert default_settings.observability.service_name == "i4g-backend"

    _set_env(monkeypatch, "I4G_OBSERVABILITY__STATSD_HOST", "127.0.0.1")
    _set_env(monkeypatch, "I4G_OBSERVABILITY__STATSD_PORT", "18125")
    _set_env(monkeypatch, "I4G_OBSERVABILITY__STATSD_PREFIX", "core")
    _set_env(monkeypatch, "I4G_OBSERVABILITY__SERVICE_NAME", "hybrid-search")

    overridden = reload_settings(env="dev")
    assert overridden.observability.statsd_host == "127.0.0.1"
    assert overridden.observability.statsd_port == 18125
    assert overridden.observability.statsd_prefix == "core"
    assert overridden.observability.service_name == "hybrid-search"


# ── D66: AccountJobSettings ────────────────────────────────────────────


def test_account_job_defaults(monkeypatch: object) -> None:
    """Verify AccountJobSettings defaults when no env vars are set."""

    for name in (
        "I4G_ACCOUNT_JOB__WINDOW_DAYS",
        "I4G_ACCOUNT_JOB__TOP_K",
        "I4G_ACCOUNT_JOB__DRY_RUN",
        "I4G_ACCOUNT_JOB__OUTPUT_FORMATS",
        "I4G_ACCOUNT_JOB__CATEGORIES",
        "I4G_ACCOUNT_JOB__INCLUDE_SOURCES",
        "I4G_ACCOUNT_JOB__START_TIME",
        "I4G_ACCOUNT_JOB__END_TIME",
    ):
        _clear_env(monkeypatch, name)

    settings = reload_settings(env="dev")
    assert settings.account_job.window_days == 15
    assert settings.account_job.top_k == 200
    assert settings.account_job.dry_run is False
    assert settings.account_job.include_sources is True
    assert settings.account_job.output_formats == []
    assert settings.account_job.categories == []
    assert settings.account_job.start_time is None
    assert settings.account_job.end_time is None


def test_account_job_env_overrides(monkeypatch: object) -> None:
    """Verify AccountJobSettings respects env var overrides."""

    _set_env(monkeypatch, "I4G_ACCOUNT_JOB__WINDOW_DAYS", "30")
    _set_env(monkeypatch, "I4G_ACCOUNT_JOB__TOP_K", "50")
    _set_env(monkeypatch, "I4G_ACCOUNT_JOB__DRY_RUN", "true")
    _set_env(monkeypatch, "I4G_ACCOUNT_JOB__INCLUDE_SOURCES", "false")
    _set_env(monkeypatch, "I4G_ACCOUNT_JOB__CATEGORIES", '["bank","crypto"]')

    settings = reload_settings(env="dev")
    assert settings.account_job.window_days == 30
    assert settings.account_job.top_k == 50
    assert settings.account_job.dry_run is True
    assert settings.account_job.include_sources is False


# ── D67: IntakeJobSettings ─────────────────────────────────────────────


def test_intake_job_defaults(monkeypatch: object) -> None:
    """Verify IntakeJobSettings defaults when no env vars are set."""

    for name in (
        "I4G_INTAKE__ID",
        "I4G_INTAKE__JOB_ID",
        "I4G_INTAKE__API_BASE",
        "I4G_INTAKE__API_KEY",
    ):
        _clear_env(monkeypatch, name)

    settings = reload_settings(env="dev")
    assert settings.intake.id is None
    assert settings.intake.job_id is None
    assert settings.intake.api_base is None
    assert settings.intake.api_key is None


def test_intake_job_env_overrides(monkeypatch: object) -> None:
    """Verify IntakeJobSettings respects env var overrides."""

    _set_env(monkeypatch, "I4G_INTAKE__ID", "intake-123")
    _set_env(monkeypatch, "I4G_INTAKE__JOB_ID", "job-456")
    _set_env(monkeypatch, "I4G_INTAKE__API_BASE", "https://api.example.com")
    _set_env(monkeypatch, "I4G_INTAKE__API_KEY", "secret-key")

    settings = reload_settings(env="dev")
    assert settings.intake.id == "intake-123"
    assert settings.intake.job_id == "job-456"
    assert settings.intake.api_base == "https://api.example.com"
    assert settings.intake.api_key == "secret-key"


# ── D67: RuntimeSettings fallback_dir ──────────────────────────────────


def test_runtime_fallback_dir_default(monkeypatch: object) -> None:
    """Verify runtime fallback_dir defaults to /tmp/i4g/evidence."""

    _clear_env(monkeypatch, "I4G_RUNTIME__FALLBACK_DIR")

    settings = reload_settings(env="dev")
    assert settings.runtime.fallback_dir == Path("/tmp/i4g/evidence")


def test_runtime_fallback_dir_override(monkeypatch: object, tmp_path: Path) -> None:
    """Verify runtime fallback_dir respects env override."""

    _set_env(monkeypatch, "I4G_RUNTIME__FALLBACK_DIR", str(tmp_path / "custom"))

    settings = reload_settings(env="dev")
    assert settings.runtime.fallback_dir == tmp_path / "custom"


def test_gcs_dataset_path_preserved(monkeypatch: object) -> None:
    """GCS URIs (gs://…) must not be coerced into local Path objects."""

    gcs_uri = "gs://i4g-dev-data-bundles/2025-12-17/legacy_azure/search_exports/vertex"
    _clear_env(monkeypatch, "I4G_INGEST__JSONL_PATH", "I4G_ENV")
    _set_env(monkeypatch, "I4G_ENV", "dev")
    _set_env(monkeypatch, "I4G_INGEST__JSONL_PATH", gcs_uri)

    settings = reload_settings(env="dev")
    assert str(settings.ingestion.dataset_path) == gcs_uri


def test_retention_days_override(monkeypatch: object) -> None:
    """storage.retention_days responds to I4G_STORAGE__RETENTION_DAYS."""

    _clear_env(monkeypatch, "I4G_STORAGE__RETENTION_DAYS", "STORAGE__RETENTION_DAYS", "STORAGE_RETENTION_DAYS")
    _set_env(monkeypatch, "I4G_STORAGE__RETENTION_DAYS", "45")

    settings = reload_settings(env="dev")
    assert settings.storage.retention_days == 45


def test_retention_grace_days_override(monkeypatch: object) -> None:
    """storage.retention_grace_days responds to I4G_STORAGE__RETENTION_GRACE_DAYS."""

    _clear_env(
        monkeypatch,
        "I4G_STORAGE__RETENTION_GRACE_DAYS",
        "STORAGE__RETENTION_GRACE_DAYS",
        "STORAGE_RETENTION_GRACE_DAYS",
    )
    _set_env(monkeypatch, "I4G_STORAGE__RETENTION_GRACE_DAYS", "14")

    settings = reload_settings(env="dev")
    assert settings.storage.retention_grace_days == 14


def test_iap_backend_audience_override(monkeypatch: object) -> None:
    """identity.iap_backend_audience responds to I4G_IDENTITY__IAP_BACKEND_AUDIENCE."""

    _clear_env(
        monkeypatch,
        "I4G_IDENTITY__IAP_BACKEND_AUDIENCE",
        "IDENTITY__IAP_BACKEND_AUDIENCE",
        "IDENTITY_IAP_BACKEND_AUDIENCE",
    )
    aud = "/projects/123456/global/backendServices/789012"
    _set_env(monkeypatch, "I4G_IDENTITY__IAP_BACKEND_AUDIENCE", aud)

    settings = reload_settings(env="dev")
    assert settings.identity.iap_backend_audience == aud


def test_iap_backend_audience_default_none(monkeypatch: object) -> None:
    """identity.iap_backend_audience defaults to None when not set."""

    _clear_env(
        monkeypatch,
        "I4G_IDENTITY__IAP_BACKEND_AUDIENCE",
        "IDENTITY__IAP_BACKEND_AUDIENCE",
        "IDENTITY_IAP_BACKEND_AUDIENCE",
    )

    settings = reload_settings(env="dev")
    assert settings.identity.iap_backend_audience is None


def test_ssi_service_url_override(monkeypatch: object) -> None:
    """ssi.service_url responds to I4G_SSI__SERVICE_URL."""

    _clear_env(
        monkeypatch,
        "I4G_SSI__SERVICE_URL",
        "SSI__SERVICE_URL",
        "SSI_SERVICE_URL",
    )
    _set_env(monkeypatch, "I4G_SSI__SERVICE_URL", "https://ssi-svc-custom.run.app")

    settings = reload_settings(env="dev")
    assert settings.ssi.service_url == "https://ssi-svc-custom.run.app"


def test_ssi_defaults(monkeypatch: object) -> None:
    """ssi settings have sensible defaults."""

    _clear_env(
        monkeypatch,
        "I4G_SSI__SERVICE_URL",
        "SSI__SERVICE_URL",
        "SSI_SERVICE_URL",
        "I4G_SSI__CORE_API_URL",
        "SSI__CORE_API_URL",
        "SSI_CORE_API_URL",
        "I4G_SSI__PLAYBOOK_DIR",
        "SSI__PLAYBOOK_DIR",
        "SSI_PLAYBOOK_DIR",
    )

    settings = reload_settings(env="dev")
    assert settings.ssi.service_url == ""
    assert settings.ssi.core_api_url == "https://api.intelligenceforgood.org"
    assert settings.ssi.playbook_dir  # should have a default value


def test_ssi_evidence_bucket_override(monkeypatch: object) -> None:
    """storage.ssi_evidence_bucket responds to I4G_STORAGE__SSI_EVIDENCE_BUCKET."""

    _clear_env(
        monkeypatch,
        "I4G_STORAGE__SSI_EVIDENCE_BUCKET",
        "STORAGE__SSI_EVIDENCE_BUCKET",
        "STORAGE_SSI_EVIDENCE_BUCKET",
    )
    _set_env(monkeypatch, "I4G_STORAGE__SSI_EVIDENCE_BUCKET", "i4g-dev-ssi-evidence")

    settings = reload_settings(env="dev")
    assert settings.storage.ssi_evidence_bucket == "i4g-dev-ssi-evidence"


def test_ssi_evidence_bucket_default_none(monkeypatch: object) -> None:
    """storage.ssi_evidence_bucket defaults to None when not set."""

    _clear_env(
        monkeypatch,
        "I4G_STORAGE__SSI_EVIDENCE_BUCKET",
        "STORAGE__SSI_EVIDENCE_BUCKET",
        "STORAGE_SSI_EVIDENCE_BUCKET",
    )

    settings = reload_settings(env="dev")
    assert settings.storage.ssi_evidence_bucket is None


def test_ssi_evidence_prefix_override(monkeypatch: object) -> None:
    """storage.ssi_evidence_prefix responds to I4G_STORAGE__SSI_EVIDENCE_PREFIX."""

    _clear_env(
        monkeypatch,
        "I4G_STORAGE__SSI_EVIDENCE_PREFIX",
        "STORAGE__SSI_EVIDENCE_PREFIX",
        "STORAGE_SSI_EVIDENCE_PREFIX",
    )
    _set_env(monkeypatch, "I4G_STORAGE__SSI_EVIDENCE_PREFIX", "scans/v2")

    settings = reload_settings(env="dev")
    assert settings.storage.ssi_evidence_prefix == "scans/v2"


def test_ssi_evidence_prefix_default(monkeypatch: object) -> None:
    """storage.ssi_evidence_prefix defaults to 'investigations'."""

    _clear_env(
        monkeypatch,
        "I4G_STORAGE__SSI_EVIDENCE_PREFIX",
        "STORAGE__SSI_EVIDENCE_PREFIX",
        "STORAGE_SSI_EVIDENCE_PREFIX",
    )

    settings = reload_settings(env="dev")
    assert settings.storage.ssi_evidence_prefix == "investigations"


# ---------------------------------------------------------------------------
# SSI settings (service-only, Phase 3.0.12)
# ---------------------------------------------------------------------------


def test_ssi_service_url_default(monkeypatch: object) -> None:
    """ssi.service_url defaults to empty string."""

    _clear_env(
        monkeypatch,
        "I4G_SSI__SERVICE_URL",
        "SSI_SERVICE_URL",
        "SSI__SERVICE_URL",
    )

    settings = reload_settings(env="dev")
    assert settings.ssi.service_url == ""


def test_ssi_service_url_env_override(monkeypatch: object) -> None:
    """ssi.service_url can be set via env var."""

    _clear_env(
        monkeypatch,
        "I4G_SSI__SERVICE_URL",
        "SSI_SERVICE_URL",
        "SSI__SERVICE_URL",
    )
    _set_env(monkeypatch, "SSI__SERVICE_URL", "https://ssi-svc-abc123.run.app")

    settings = reload_settings(env="dev")
    assert settings.ssi.service_url == "https://ssi-svc-abc123.run.app"
