"""Unit tests for build_inference_client factory."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from i4g.settings.config import reload_settings


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("I4G_SETTINGS_FILE", raising=False)
    monkeypatch.setattr(
        "i4g.settings.config.LOCAL_CONFIG_FILE",
        tmp_path / "settings.local.toml",
    )
    for var in (
        "I4G_ML__INFERENCE_BACKEND",
        "I4G_ML__PLATFORM_BASE_URL",
        "ML_INFERENCE_BACKEND",
        "ML_PLATFORM_BASE_URL",
    ):
        monkeypatch.delenv(var, raising=False)


def test_build_inference_client_returns_llm_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """When inference_backend is 'llm', factory returns the LLM client."""
    settings = reload_settings(env="local")
    with patch("i4g.services.factories.get_settings", return_value=settings):
        from i4g.services.factories import build_inference_client

        client = build_inference_client()
        # Should NOT be MLPlatformClient — it should be the LLM fallback
        assert not hasattr(client, "send_feedback")


def test_build_inference_client_returns_ml_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    """When inference_backend is 'ml_platform', factory returns MLPlatformClient."""
    monkeypatch.setenv("I4G_ML__INFERENCE_BACKEND", "ml_platform")
    monkeypatch.setenv("I4G_ML__PLATFORM_BASE_URL", "http://ml.example.com")
    settings = reload_settings(env="local")
    with patch("i4g.services.factories.get_settings", return_value=settings):
        from i4g.services.factories import build_inference_client

        client = build_inference_client()
        from i4g.ml.client import MLPlatformClient

        assert isinstance(client, MLPlatformClient)
