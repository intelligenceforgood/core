"""Unit tests for ExtractionSettings configuration."""

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
        "I4G_EXTRACTION__ENABLED_MODULES",
        "I4G_EXTRACTION__LLM_DELAY_SECONDS",
        "I4G_EXTRACTION__BATCH_CONCURRENCY",
        "I4G_EXTRACTION__GATE_PERSON",
        "I4G_EXTRACTION__GATE_WALLET_ADDRESS",
    ):
        monkeypatch.delenv(var, raising=False)


def test_extraction_defaults() -> None:
    settings = reload_settings(env="local")

    assert settings.extraction.enabled_modules == ["regex", "llm"]
    assert settings.extraction.llm_delay_seconds == 0.5
    assert settings.extraction.batch_concurrency == 1


def test_extraction_confidence_gates() -> None:
    settings = reload_settings(env="local")
    gates = settings.extraction.confidence_gates()

    assert gates["person"] == 0.6
    assert gates["organization"] == 0.6
    assert gates["wallet_address"] == 0.5
    assert gates["crypto_token"] == 0.4
    assert gates["location"] == 0.5


def test_extraction_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("I4G_EXTRACTION__GATE_PERSON", "0.8")
    settings = reload_settings(env="local")

    gates = settings.extraction.confidence_gates()
    assert gates["person"] == 0.8
