"""Unit tests for AnalyticsSettings configuration."""

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
        "I4G_ANALYTICS__REFRESH_INTERVAL_MINUTES",
        "I4G_ANALYTICS__LOSS_LINKAGE_CONFIDENCE_THRESHOLD",
    ):
        monkeypatch.delenv(var, raising=False)


def test_analytics_defaults() -> None:
    """AnalyticsSettings defaults match expected values."""
    settings = reload_settings(env="local")

    assert settings.analytics.refresh_interval_minutes == 15
    assert settings.analytics.loss_linkage_confidence_threshold == 0.6
    assert isinstance(settings.analytics.campaign_risk_weights, dict)
    assert settings.analytics.campaign_risk_weights["case_count"] == 0.15
    assert settings.analytics.campaign_risk_weights["loss_sum"] == 0.30
    assert settings.analytics.campaign_risk_weights["avg_risk"] == 0.25
    assert settings.analytics.campaign_risk_weights["recency"] == 0.15
    assert settings.analytics.campaign_risk_weights["indicator_diversity"] == 0.15


def test_refresh_interval_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """I4G_ANALYTICS__REFRESH_INTERVAL_MINUTES overrides the default."""
    monkeypatch.setenv("I4G_ANALYTICS__REFRESH_INTERVAL_MINUTES", "30")

    settings = reload_settings(env="dev")

    assert settings.analytics.refresh_interval_minutes == 30


def test_confidence_threshold_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """I4G_ANALYTICS__LOSS_LINKAGE_CONFIDENCE_THRESHOLD overrides the default."""
    monkeypatch.setenv("I4G_ANALYTICS__LOSS_LINKAGE_CONFIDENCE_THRESHOLD", "0.8")

    settings = reload_settings(env="dev")

    assert settings.analytics.loss_linkage_confidence_threshold == 0.8
