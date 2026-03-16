"""Unit tests for AutoInvestigateSettings configuration."""

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
        "I4G_AUTO_INVESTIGATE__ENABLED",
        "I4G_AUTO_INVESTIGATE__STALENESS_DAYS",
        "I4G_AUTO_INVESTIGATE__MAX_CONCURRENT",
        "I4G_AUTO_INVESTIGATE__DOMAIN_BLOCKLIST",
    ):
        monkeypatch.delenv(var, raising=False)


def test_defaults() -> None:
    """AutoInvestigateSettings defaults match expected values."""
    settings = reload_settings(env="local")

    assert settings.auto_investigate.enabled is False
    assert settings.auto_investigate.staleness_days == 30
    assert settings.auto_investigate.max_concurrent == 3
    assert settings.auto_investigate.domain_blocklist == []


def test_enabled_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """I4G_AUTO_INVESTIGATE__ENABLED env var overrides default."""
    monkeypatch.setenv("I4G_AUTO_INVESTIGATE__ENABLED", "true")

    settings = reload_settings(env="dev")

    assert settings.auto_investigate.enabled is True


def test_staleness_days_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """I4G_AUTO_INVESTIGATE__STALENESS_DAYS env var overrides default."""
    monkeypatch.setenv("I4G_AUTO_INVESTIGATE__STALENESS_DAYS", "7")

    settings = reload_settings(env="dev")

    assert settings.auto_investigate.staleness_days == 7


def test_domain_blocklist_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """I4G_AUTO_INVESTIGATE__DOMAIN_BLOCKLIST env var overrides default."""
    monkeypatch.setenv("I4G_AUTO_INVESTIGATE__DOMAIN_BLOCKLIST", '["google.com","facebook.com"]')

    settings = reload_settings(env="dev")

    assert settings.auto_investigate.domain_blocklist == ["google.com", "facebook.com"]
