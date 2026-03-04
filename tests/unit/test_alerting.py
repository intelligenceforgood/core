"""Unit tests for the AlertingService (F48, F49, F50)."""

from __future__ import annotations

import time

import pytest

from i4g.services.alerting import AlertingService, get_alerting_service, reset_alerting_service

# ---------------------------------------------------------------------------
# Stub observability for test isolation
# ---------------------------------------------------------------------------


class StubObservability:
    """Captures metrics and events without side effects."""

    def __init__(self) -> None:
        self.increments: list[tuple[str, float, dict]] = []
        self.events: list[tuple[str, dict]] = []
        self.timings: list[tuple[str, float, dict]] = []

    def increment(self, metric: str, *, value: float = 1.0, tags: dict | None = None) -> None:
        self.increments.append((metric, value, tags or {}))

    def emit_event(self, event: str, **fields) -> None:
        self.events.append((event, fields))

    def record_timing(self, metric: str, value_ms: float, *, tags: dict | None = None) -> None:
        self.timings.append((metric, value_ms, tags or {}))


class FakeSettings:
    """Minimal stand-in for Settings with observability section."""

    class ObservabilitySection:
        detokenization_alert_threshold: int = 3  # low threshold for testing
        ingestion_error_rate_threshold: float = 0.10
        dossier_stuck_timeout_minutes: int = 1  # 1 min for fast tests

    observability = ObservabilitySection()


@pytest.fixture()
def stub_obs() -> StubObservability:
    return StubObservability()


@pytest.fixture()
def alerting(stub_obs: StubObservability) -> AlertingService:
    svc = AlertingService.__new__(AlertingService)
    import threading
    from collections import defaultdict

    svc._settings = FakeSettings()
    svc._obs = stub_obs
    svc._lock = threading.Lock()
    svc._detokenization_windows = defaultdict(
        lambda: __import__("i4g.services.alerting", fromlist=["_AccessWindow"])._AccessWindow()
    )
    return svc


# ===================================================================
# F48 — Detokenization rate alerting
# ===================================================================


class TestDetokenizationRateAlerts:
    def test_no_alert_below_threshold(self, alerting: AlertingService, stub_obs: StubObservability):
        """Calls below threshold should not fire an alert."""
        for _ in range(3):
            result = alerting.check_detokenization_rate(actor="alice")
        assert result is False
        alert_events = [e for e in stub_obs.events if "threshold_exceeded" in e[0]]
        assert len(alert_events) == 0

    def test_alert_fires_above_threshold(self, alerting: AlertingService, stub_obs: StubObservability):
        """Fourth call exceeds threshold of 3, should fire alert."""
        for _ in range(3):
            alerting.check_detokenization_rate(actor="bob")
        result = alerting.check_detokenization_rate(actor="bob")
        assert result is True
        alert_events = [e for e in stub_obs.events if "threshold_exceeded" in e[0]]
        assert len(alert_events) == 1
        payload = alert_events[0][1]
        assert payload["alert"] is True
        assert payload["alert_type"] == "pii_access"
        assert payload["actor"] == "bob"
        assert payload["count"] == 4

    def test_different_actors_tracked_separately(self, alerting: AlertingService, stub_obs: StubObservability):
        """Each actor has an independent sliding window."""
        for _ in range(4):
            alerting.check_detokenization_rate(actor="carol")
        result_dave = alerting.check_detokenization_rate(actor="dave")
        assert result_dave is False

    def test_case_id_forwarded(self, alerting: AlertingService, stub_obs: StubObservability):
        """case_id is included in alert metadata when provided."""
        for _ in range(4):
            alerting.check_detokenization_rate(actor="eve", case_id="CASE-001")
        alert_events = [e for e in stub_obs.events if "threshold_exceeded" in e[0]]
        assert alert_events[0][1]["case_id"] == "CASE-001"

    def test_check_metric_always_emitted(self, alerting: AlertingService, stub_obs: StubObservability):
        """Every call emits a check counter."""
        alerting.check_detokenization_rate(actor="frank")
        check_metrics = [m for m in stub_obs.increments if m[0] == "alerting.detokenization.check"]
        assert len(check_metrics) == 1
        assert check_metrics[0][2]["actor"] == "frank"


# ===================================================================
# F49 — Ingestion error rate alerting
# ===================================================================


class TestIngestionErrorRateAlerts:
    def test_no_alert_when_rate_below_threshold(self, alerting: AlertingService, stub_obs: StubObservability):
        """Error rate of 5% is below 10% threshold — no alert."""
        result = alerting.check_ingestion_error_rate(processed=100, failures=5, dataset="test-ds")
        assert result is False

    def test_alert_fires_above_threshold(self, alerting: AlertingService, stub_obs: StubObservability):
        """Error rate of 20% is above 10% threshold — alert fires."""
        result = alerting.check_ingestion_error_rate(processed=100, failures=20, dataset="bad-ds", run_id="run-99")
        assert result is True
        alert_events = [e for e in stub_obs.events if "error_rate_exceeded" in e[0]]
        assert len(alert_events) == 1
        payload = alert_events[0][1]
        assert payload["alert"] is True
        assert payload["alert_type"] == "ingestion_failure"
        assert payload["error_rate"] == 0.2
        assert payload["dataset"] == "bad-ds"
        assert payload["run_id"] == "run-99"

    def test_no_alert_with_zero_processed(self, alerting: AlertingService, stub_obs: StubObservability):
        """Edge case: 0 records processed should not alert or divide by zero."""
        result = alerting.check_ingestion_error_rate(processed=0, failures=0)
        assert result is False

    def test_critical_severity_above_50_percent(self, alerting: AlertingService, stub_obs: StubObservability):
        """Error rate > 50% should emit severity=critical."""
        alerting.check_ingestion_error_rate(processed=10, failures=8)
        alert_events = [e for e in stub_obs.events if "error_rate_exceeded" in e[0]]
        assert alert_events[0][1]["severity"] == "critical"

    def test_warning_severity_below_50_percent(self, alerting: AlertingService, stub_obs: StubObservability):
        """Error rate 11-50% should emit severity=warning."""
        alerting.check_ingestion_error_rate(processed=100, failures=15)
        alert_events = [e for e in stub_obs.events if "error_rate_exceeded" in e[0]]
        assert alert_events[0][1]["severity"] == "warning"


# ===================================================================
# F50 — Dossier generation alerting
# ===================================================================


class TestDossierAlerts:
    def test_no_alert_when_within_timeout(self, alerting: AlertingService, stub_obs: StubObservability):
        """Job started 10 seconds ago — well within 1-min timeout for tests."""
        result = alerting.check_dossier_job(started_at=time.time() - 10, job_id="j-1", status="processing")
        assert result is False

    def test_alert_fires_when_stuck(self, alerting: AlertingService, stub_obs: StubObservability):
        """Job started 90 seconds ago exceeds 1-min timeout."""
        result = alerting.check_dossier_job(started_at=time.time() - 90, job_id="j-2", status="processing")
        assert result is True
        events = [e for e in stub_obs.events if "stuck_job" in e[0]]
        assert len(events) == 1
        assert events[0][1]["alert_type"] == "dossier_stuck"
        assert events[0][1]["job_id"] == "j-2"

    def test_no_alert_for_finished_jobs(self, alerting: AlertingService, stub_obs: StubObservability):
        """Finished jobs should not trigger stuck alerts even if old."""
        result = alerting.check_dossier_job(started_at=time.time() - 3600, job_id="j-3", status="finished")
        assert result is False

    def test_no_alert_for_failed_status(self, alerting: AlertingService, stub_obs: StubObservability):
        """Failed jobs should also be excluded from stuck alerts."""
        result = alerting.check_dossier_job(started_at=time.time() - 3600, job_id="j-4", status="failed")
        assert result is False

    def test_report_dossier_failure(self, alerting: AlertingService, stub_obs: StubObservability):
        """report_dossier_failure emits a critical alert event."""
        alerting.report_dossier_failure(job_id="j-5", error="timeout", review_id="REV-001")
        events = [e for e in stub_obs.events if "job_failed" in e[0]]
        assert len(events) == 1
        assert events[0][1]["severity"] == "critical"
        assert events[0][1]["review_id"] == "REV-001"


# ===================================================================
# Singleton management
# ===================================================================


class TestSingleton:
    def test_reset_clears_singleton(self):
        """reset_alerting_service should clear the cached instance."""
        reset_alerting_service()
        svc1 = get_alerting_service()
        reset_alerting_service()
        svc2 = get_alerting_service()
        assert svc1 is not svc2
        reset_alerting_service()

    def test_reset_clears_internal_state(self, alerting: AlertingService, stub_obs: StubObservability):
        """reset() clears sliding windows."""
        for _ in range(4):
            alerting.check_detokenization_rate(actor="grace")
        alerting.reset()
        result = alerting.check_detokenization_rate(actor="grace")
        assert result is False
