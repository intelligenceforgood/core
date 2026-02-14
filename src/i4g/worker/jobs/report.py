"""Cloud Run job entrypoint for batch report generation."""

from __future__ import annotations

import logging
import sys
import time

from i4g.services.alerting import get_alerting_service
from i4g.services.factories import build_review_store
from i4g.settings import get_settings
from i4g.task_status import TaskStatusReporter
from i4g.worker.logging import configure_job_logging
from i4g.worker.tasks import generate_report_for_case

LOGGER = logging.getLogger("i4g.worker.jobs.report")


def _resolve_review_ids(limit: int, *, settings=None) -> list[str]:
    s = settings or get_settings()
    explicit = s.report.review_ids
    if explicit:
        return [value.strip() for value in explicit.split(",") if value.strip()]

    target_status = s.report.target_status
    store = build_review_store()
    queue = store.get_queue(status=target_status, limit=limit)
    return [item["review_id"] for item in queue]


def main() -> int:
    """Entry point executed by the Cloud Run job container."""

    settings = get_settings()
    configure_job_logging(settings)

    batch_limit = settings.report.batch_limit
    dry_run = settings.report.dry_run

    LOGGER.info("Starting report job: batch_limit=%s dry_run=%s", batch_limit, dry_run)

    reporter = TaskStatusReporter()

    review_ids = _resolve_review_ids(limit=batch_limit, settings=settings)
    if not review_ids:
        LOGGER.info("No review IDs resolved; nothing to do")
        if reporter.is_enabled():
            reporter.update(status="finished", message="No reviews to process", processed=0)
        return 0

    total = len(review_ids)
    LOGGER.info("Resolved %s review ID(s) for processing", total)
    if reporter.is_enabled():
        reporter.update(status="started", message=f"Processing {total} reviews", total=total, dry_run=dry_run)

    alerting = get_alerting_service(settings=settings)
    job_started_at = time.time()
    task_id = reporter.task_id

    store = build_review_store()
    successes = 0
    failures = 0

    for idx, review_id in enumerate(review_ids, 1):
        if dry_run:
            LOGGER.info("Dry run enabled; would generate report for %s", review_id)
            successes += 1
        else:
            result = generate_report_for_case(review_id, store=store)
            if result.startswith("error:"):
                failures += 1
                LOGGER.error("Report generation failed for %s: %s", review_id, result)
                alerting.report_dossier_failure(
                    job_id=task_id,
                    error=result,
                    review_id=review_id,
                )
            else:
                successes += 1
                LOGGER.info("Report generated for %s → %s", review_id, result)

        # F50: periodic stuck-job check
        alerting.check_dossier_job(started_at=job_started_at, job_id=task_id, status="processing")

        if reporter.is_enabled() and (idx % 5 == 0 or idx == total):
            reporter.update(
                status="processing",
                message=f"Processed {idx}/{total} reviews",
                progress=idx,
                total=total,
                successes=successes,
                failures=failures,
            )

    status = "finished" if failures == 0 else "partial"
    LOGGER.info("Report batch complete: successes=%s failures=%s", successes, failures)
    if reporter.is_enabled():
        reporter.update(
            status=status,
            message=f"Report job {status}: {successes} succeeded, {failures} failed",
            processed=successes + failures,
            successes=successes,
            failures=failures,
        )

    return 0 if failures == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
