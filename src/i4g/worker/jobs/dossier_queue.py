"""Cloud Run job entrypoint for processing dossier queue entries."""

from __future__ import annotations

import logging
import sys

from i4g.reports.dossier_queue_processor import DossierQueueProcessor, QueueProcessSummary
from i4g.settings import get_settings
from i4g.task_status import TaskStatusReporter
from i4g.worker.logging import configure_job_logging

LOGGER = logging.getLogger("i4g.worker.jobs.dossier_queue")


def run_job(
    *,
    batch_size: int,
    dry_run: bool,
    processor: DossierQueueProcessor | None = None,
    reporter: TaskStatusReporter | None = None,
) -> QueueProcessSummary:
    """Run a single processor batch and return the summary (test helper)."""

    runner = processor or DossierQueueProcessor()
    return runner.process_batch(batch_size=batch_size, dry_run=dry_run, reporter=reporter)


def main() -> int:
    """Entry point executed by Cloud Run jobs and local CLI."""

    settings = get_settings()
    configure_job_logging(settings)
    batch_size = settings.dossier_job.batch_size
    dry_run = settings.dossier_job.dry_run

    LOGGER.info("Starting dossier queue job: batch_size=%s dry_run=%s", batch_size, dry_run)
    reporter = TaskStatusReporter()
    if reporter.is_enabled():
        reporter.update(status="started", message="Dossier job started", batch_size=batch_size, dry_run=dry_run)

    summary = run_job(batch_size=batch_size, dry_run=dry_run, reporter=reporter if reporter.is_enabled() else None)

    LOGGER.info(
        "Dossier queue job complete: processed=%s completed=%s failed=%s dry_run=%s",
        summary.processed,
        summary.completed,
        summary.failed,
        summary.dry_run,
    )

    if reporter.is_enabled():
        reporter.update(
            status="finished" if summary.failed == 0 else "partial",
            message="Dossier job complete",
            processed=summary.processed,
            completed=summary.completed,
            failed=summary.failed,
            dry_run=summary.dry_run,
        )

    return 0 if summary.failed == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
