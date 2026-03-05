"""Unit tests for FeedbackSettings configuration."""

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
    # Ensure feedback env vars start clean.
    for var in (
        "I4G_FEEDBACK__ENABLED",
        "I4G_FEEDBACK__SHEET_ID",
        "FEEDBACK_ENABLED",
        "FEEDBACK__ENABLED",
        "FEEDBACK_SHEET_ID",
        "FEEDBACK__SHEET_ID",
    ):
        monkeypatch.delenv(var, raising=False)


def test_feedback_defaults() -> None:
    """Feedback feature is enabled and sheet_id is empty by default."""

    settings = reload_settings(env="local")

    assert settings.feedback.enabled is True
    assert settings.feedback.sheet_id == ""


def test_feedback_sheet_id_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """I4G_FEEDBACK__SHEET_ID sets the Sheet ID."""

    sheet_id = "1o8iSyLtFbSxdqEtT-L7OQvSqKTealP1H8f0VZzZKTw8"
    monkeypatch.setenv("I4G_FEEDBACK__SHEET_ID", sheet_id)

    settings = reload_settings(env="dev")

    assert settings.feedback.sheet_id == sheet_id


def test_feedback_enabled_override_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """I4G_FEEDBACK__ENABLED=false disables the feedback feature."""

    monkeypatch.setenv("I4G_FEEDBACK__ENABLED", "false")

    settings = reload_settings(env="dev")

    assert settings.feedback.enabled is False


def test_feedback_enabled_override_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """I4G_FEEDBACK__ENABLED=true keeps feedback enabled."""

    monkeypatch.setenv("I4G_FEEDBACK__ENABLED", "true")

    settings = reload_settings(env="dev")

    assert settings.feedback.enabled is True


def test_feedback_sheet_id_empty_by_default_in_dev(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sheet ID is not injected by config files — must be supplied via env."""

    settings = reload_settings(env="dev")

    # When no env var is set, sheet_id falls back to empty string.
    assert settings.feedback.sheet_id == ""
