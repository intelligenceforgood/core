"""Unit tests for Sprint 5 settings — AnalyticsSettings extensions + EnrichmentSettings."""

from __future__ import annotations

from pathlib import Path

import pytest

from i4g.settings.config import reload_settings


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Prevent local config files from affecting defaults."""
    monkeypatch.delenv("I4G_SETTINGS_FILE", raising=False)
    monkeypatch.setattr(
        "i4g.settings.config.LOCAL_CONFIG_FILE",
        tmp_path / "settings.local.toml",
    )
    for var in (
        "I4G_ANALYTICS__WATCHLIST_CHECK_INTERVAL_MINUTES",
        "I4G_ANALYTICS__INFRASTRUCTURE_CLUSTERING_INTERVAL_HOURS",
        "I4G_ANALYTICS__SCHEDULED_REPORT_CHECK_INTERVAL_MINUTES",
        "I4G_ENRICHMENT__SECURITYTRAILS_API_KEY",
        "I4G_ENRICHMENT__TAKEDOWN_CHECK_INTERVAL_HOURS",
        "I4G_ENRICHMENT__TAKEDOWN_MAX_URLS_PER_RUN",
    ):
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# AnalyticsSettings Sprint 5 fields
# ---------------------------------------------------------------------------


def test_watchlist_check_interval_default() -> None:
    """Watchlist check interval defaults to 30 minutes."""
    settings = reload_settings(env="local")
    assert settings.analytics.watchlist_check_interval_minutes == 30


def test_watchlist_check_interval_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """I4G_ANALYTICS__WATCHLIST_CHECK_INTERVAL_MINUTES overrides the default."""
    monkeypatch.setenv("I4G_ANALYTICS__WATCHLIST_CHECK_INTERVAL_MINUTES", "10")
    settings = reload_settings(env="dev")
    assert settings.analytics.watchlist_check_interval_minutes == 10


def test_infrastructure_clustering_interval_default() -> None:
    """Infrastructure clustering interval defaults to 6 hours."""
    settings = reload_settings(env="local")
    assert settings.analytics.infrastructure_clustering_interval_hours == 6


def test_infrastructure_clustering_interval_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """I4G_ANALYTICS__INFRASTRUCTURE_CLUSTERING_INTERVAL_HOURS overrides."""
    monkeypatch.setenv("I4G_ANALYTICS__INFRASTRUCTURE_CLUSTERING_INTERVAL_HOURS", "12")
    settings = reload_settings(env="dev")
    assert settings.analytics.infrastructure_clustering_interval_hours == 12


def test_scheduled_report_interval_default() -> None:
    """Scheduled report check interval defaults to 15 minutes."""
    settings = reload_settings(env="local")
    assert settings.analytics.scheduled_report_check_interval_minutes == 15


def test_scheduled_report_interval_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """I4G_ANALYTICS__SCHEDULED_REPORT_CHECK_INTERVAL_MINUTES overrides."""
    monkeypatch.setenv("I4G_ANALYTICS__SCHEDULED_REPORT_CHECK_INTERVAL_MINUTES", "5")
    settings = reload_settings(env="dev")
    assert settings.analytics.scheduled_report_check_interval_minutes == 5


# ---------------------------------------------------------------------------
# EnrichmentSettings
# ---------------------------------------------------------------------------


def test_enrichment_defaults() -> None:
    """EnrichmentSettings has expected defaults."""
    settings = reload_settings(env="local")
    assert settings.enrichment.securitytrails_api_key == ""
    assert settings.enrichment.takedown_check_interval_hours == 12
    assert settings.enrichment.takedown_max_urls_per_run == 200


def test_enrichment_api_key_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """I4G_ENRICHMENT__SECURITYTRAILS_API_KEY overrides the default."""
    monkeypatch.setenv("I4G_ENRICHMENT__SECURITYTRAILS_API_KEY", "test-key-123")
    settings = reload_settings(env="dev")
    assert settings.enrichment.securitytrails_api_key == "test-key-123"


def test_enrichment_takedown_interval_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """I4G_ENRICHMENT__TAKEDOWN_CHECK_INTERVAL_HOURS overrides the default."""
    monkeypatch.setenv("I4G_ENRICHMENT__TAKEDOWN_CHECK_INTERVAL_HOURS", "24")
    settings = reload_settings(env="dev")
    assert settings.enrichment.takedown_check_interval_hours == 24


def test_enrichment_max_urls_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """I4G_ENRICHMENT__TAKEDOWN_MAX_URLS_PER_RUN overrides the default."""
    monkeypatch.setenv("I4G_ENRICHMENT__TAKEDOWN_MAX_URLS_PER_RUN", "500")
    settings = reload_settings(env="dev")
    assert settings.enrichment.takedown_max_urls_per_run == 500
