"""Unit tests for PhishDestroySettings defaults."""

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
        "I4G_PHISHDESTROY__DESTROYLIST__ENABLED",
        "I4G_PHISHDESTROY__DESTROYLIST__COMMIT_SHA",
        "I4G_PHISHDESTROY__DESTROYLIST__DATA_PATH",
        "PHISHDESTROY_DESTROYLIST_ENABLED",
        "PHISHDESTROY_DESTROYLIST_COMMIT_SHA",
        "PHISHDESTROY_DESTROYLIST_DATA_PATH",
    ):
        monkeypatch.delenv(var, raising=False)


def test_phishdestroy_defaults() -> None:
    """PhishDestroy destroylist settings must match the pinned defaults."""
    settings = reload_settings(env="local")

    assert settings.phishdestroy.destroylist.enabled is False
    assert settings.phishdestroy.destroylist.commit_sha == "c40cbbf527dd9e5e232090346e1a8ceab32d1683"
    assert settings.phishdestroy.destroylist.data_path.as_posix().endswith("data/data.json")


def test_phishdestroy_enabled_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enabled flag can be flipped via env var."""
    monkeypatch.setenv("I4G_PHISHDESTROY__DESTROYLIST__ENABLED", "true")
    settings = reload_settings(env="local")
    assert settings.phishdestroy.destroylist.enabled is True


def test_phishdestroy_commit_sha_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """commit_sha can be overridden via env var."""
    monkeypatch.setenv("I4G_PHISHDESTROY__DESTROYLIST__COMMIT_SHA", "abc123")
    settings = reload_settings(env="local")
    assert settings.phishdestroy.destroylist.commit_sha == "abc123"
