"""Unit tests for MlPlatformSettings configuration."""

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
        "I4G_ML__INFERENCE_BACKEND",
        "I4G_ML__PLATFORM_BASE_URL",
        "I4G_ML__PLATFORM_AUTH_METHOD",
        "I4G_ML__FALLBACK_TO_LLM",
        "ML_INFERENCE_BACKEND",
        "ML_PLATFORM_BASE_URL",
        "ML_PLATFORM_AUTH_METHOD",
        "ML_FALLBACK_TO_LLM",
    ):
        monkeypatch.delenv(var, raising=False)


def test_ml_defaults() -> None:
    """ML Platform settings default to LLM inference with fallback enabled."""
    settings = reload_settings(env="local")

    assert settings.ml.inference_backend == "llm"
    assert settings.ml.platform_base_url == ""
    assert settings.ml.platform_auth_method == "iam"
    assert settings.ml.fallback_to_llm is True


def test_ml_platform_backend_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Setting inference_backend via env var switches to ml_platform."""
    monkeypatch.setenv("I4G_ML__INFERENCE_BACKEND", "ml_platform")
    monkeypatch.setenv("I4G_ML__PLATFORM_BASE_URL", "http://ml.example.com")

    settings = reload_settings(env="local")

    assert settings.ml.inference_backend == "ml_platform"
    assert settings.ml.platform_base_url == "http://ml.example.com"


def test_ml_fallback_disabled_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fallback can be disabled via env var."""
    monkeypatch.setenv("I4G_ML__FALLBACK_TO_LLM", "false")

    settings = reload_settings(env="local")

    assert settings.ml.fallback_to_llm is False
