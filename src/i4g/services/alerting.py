"""Alerting service for security-sensitive and operational events.

Implements threshold-based alerting for:
- **F49:** Ingestion failure rate spikes
- **F50:** Stuck / failed dossier generation jobs

Alerts are emitted as structured log events with severity markers that
Cloud Monitoring log-based metrics can match on.  The structured logs use
``"alert": true`` and ``"alert_type": "<type>"`` fields so that a single
GCP log-based metric filter can capture all alert events.
"""

from __future__ import annotations

import logging
import threading
import time

from i4g.observability import Observability, get_observability
from i4g.settings import Settings, get_settings

_LOGGER = logging.getLogger("i4g.alerting")


class AlertingService:
    """Threshold-based alerting over structured logs and metrics.

    The service is intentionally lightweight and in-process.  It does **not**
    manage notification channels (email/Slack/PagerDuty) directly — those are
    wired via Cloud Monitoring alert policies that watch the log-based metrics
    emitted here (see ``infra/modules/monitoring``).
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        observability: Observability | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._obs = observability or get_observability(component="alerting", settings=self._settings)

    # ------------------------------------------------------------------
    # F49 — Ingestion failure alerting
    # ------------------------------------------------------------------

    def check_ingestion_error_rate(
        self,
        *,
        processed: int,
        failures: int,
        dataset: str | None = None,
        run_id: str | None = None,
    ) -> bool:
        """Alert if the ingestion failure rate exceeds the configured threshold.

        Intended to be called at the end of an ingestion batch.

        Args:
            processed: Total records processed (including failures).
            failures: Number of failed records.
            dataset: Dataset name for attribution.
            run_id: Ingestion run identifier.

        Returns:
            ``True`` if an alert was fired.
        """
        if processed == 0:
            return False

        error_rate = failures / processed
        threshold = self._settings.observability.ingestion_error_rate_threshold

        self._obs.increment(
            "alerting.ingestion.check",
            tags={"dataset": dataset or "unknown"},
        )
        self._obs.record_timing(
            "alerting.ingestion.error_rate",
            value_ms=error_rate * 100,  # percentage as pseudo-ms for histogram
            tags={"dataset": dataset or "unknown"},
        )

        if error_rate > threshold:
            self._obs.emit_event(
                "alerting.ingestion.error_rate_exceeded",
                alert=True,
                alert_type="ingestion_failure",
                severity="critical" if error_rate > 0.5 else "warning",
                processed=processed,
                failures=failures,
                error_rate=round(error_rate, 4),
                threshold=threshold,
                dataset=dataset,
                run_id=run_id,
            )
            self._obs.increment(
                "alerting.ingestion.alert_fired",
                tags={"dataset": dataset or "unknown"},
            )
            _LOGGER.warning(
                "Ingestion alert: error_rate=%.2f%% exceeds threshold=%.2f%% "
                "(processed=%d failures=%d dataset=%s run_id=%s)",
                error_rate * 100,
                threshold * 100,
                processed,
                failures,
                dataset,
                run_id,
            )
            return True

        return False

    # ------------------------------------------------------------------
    # F50 — Dossier generation alerting
    # ------------------------------------------------------------------

    def check_dossier_job(
        self,
        *,
        started_at: float,
        job_id: str | None = None,
        status: str = "processing",
    ) -> bool:
        """Alert if a dossier job appears stuck (running beyond the timeout).

        Args:
            started_at: Unix timestamp when the job began.
            job_id: Task/job identifier.
            status: Current status string of the job.

        Returns:
            ``True`` if an alert was fired (job is stuck).
        """
        elapsed_minutes = (time.time() - started_at) / 60.0
        timeout = self._settings.observability.dossier_stuck_timeout_minutes

        self._obs.increment("alerting.dossier.check", tags={"status": status})

        if elapsed_minutes > timeout and status not in ("finished", "partial", "failed", "completed"):
            self._obs.emit_event(
                "alerting.dossier.stuck_job",
                alert=True,
                alert_type="dossier_stuck",
                severity="warning",
                job_id=job_id,
                elapsed_minutes=round(elapsed_minutes, 1),
                timeout_minutes=timeout,
                status=status,
            )
            self._obs.increment("alerting.dossier.alert_fired", tags={"job_id": job_id or "unknown"})
            _LOGGER.warning(
                "Dossier alert: job %s stuck for %.1f min (timeout=%d min, status=%s)",
                job_id,
                elapsed_minutes,
                timeout,
                status,
            )
            return True

        return False

    def report_dossier_failure(
        self,
        *,
        job_id: str | None = None,
        error: str | None = None,
        review_id: str | None = None,
    ) -> None:
        """Emit an alert for a dossier/report job failure.

        Args:
            job_id: Task/job identifier.
            error: Error description.
            review_id: Associated review ID.
        """
        self._obs.emit_event(
            "alerting.dossier.job_failed",
            alert=True,
            alert_type="dossier_failure",
            severity="critical",
            job_id=job_id,
            error=error,
            review_id=review_id,
        )
        self._obs.increment("alerting.dossier.failure", tags={"job_id": job_id or "unknown"})
        _LOGGER.error("Dossier failure alert: job=%s review=%s error=%s", job_id, review_id, error)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear all internal state (for testing)."""


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_ALERTING_SERVICE: AlertingService | None = None
_ALERTING_LOCK = threading.Lock()


def get_alerting_service(*, settings: Settings | None = None) -> AlertingService:
    """Return the shared ``AlertingService`` singleton."""
    global _ALERTING_SERVICE
    with _ALERTING_LOCK:
        if _ALERTING_SERVICE is None:
            _ALERTING_SERVICE = AlertingService(settings=settings)
        return _ALERTING_SERVICE


def reset_alerting_service() -> None:
    """Reset the singleton (for testing)."""
    global _ALERTING_SERVICE
    with _ALERTING_LOCK:
        _ALERTING_SERVICE = None


__all__ = ["AlertingService", "get_alerting_service", "reset_alerting_service"]
