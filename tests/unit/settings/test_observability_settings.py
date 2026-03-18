"""Unit tests for ObservabilitySettings alerting thresholds (WS-8)."""

from __future__ import annotations

from i4g.settings.sections.jobs import ObservabilitySettings


class TestObservabilityAlertingDefaults:
    """Verify default values for alerting thresholds."""

    def test_default_ingestion_error_rate_threshold(self):
        settings = ObservabilitySettings()
        assert settings.ingestion_error_rate_threshold == 0.10

    def test_default_dossier_stuck_timeout(self):
        settings = ObservabilitySettings()
        assert settings.dossier_stuck_timeout_minutes == 30


class TestObservabilityAlertingOverrides:
    """Verify env-var overrides for alerting thresholds."""

    def test_ingestion_error_rate_override(self, monkeypatch):
        monkeypatch.setenv("OBS_INGESTION_ERROR_RATE_THRESHOLD", "0.05")
        settings = ObservabilitySettings()
        assert settings.ingestion_error_rate_threshold == 0.05

    def test_dossier_stuck_timeout_override(self, monkeypatch):
        monkeypatch.setenv("OBS_DOSSIER_STUCK_TIMEOUT_MINUTES", "60")
        settings = ObservabilitySettings()
        assert settings.dossier_stuck_timeout_minutes == 60
