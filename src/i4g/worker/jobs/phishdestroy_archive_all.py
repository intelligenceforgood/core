"""Cloud Run / CLI entry point for the PhishDestroy full-archive backfill job (Sprint 2 Phase D).

Iterates over every team subdirectory in the ScamIntelLogs archive root, ingesting
each via the registered adapter.  Exits with code 3 when the parse-failure rate
(fraction of ``unknown_format`` teams) exceeds the configured threshold.

Exit codes:
    0 — All teams processed; parse-failure rate within threshold.
    1 — Unhandled error during execution.
    2 — Misconfiguration (missing settings).
    3 — Parse-failure rate exceeded threshold (§7 acceptance gate).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from i4g.settings import get_settings
from i4g.worker.jobs.phishdestroy_archive import _build_archive_context
from i4g.worker.logging import configure_job_logging

LOGGER = logging.getLogger("i4g.worker.jobs.phishdestroy_archive_all")

_INGEST_JOB = "i4g-jobs-ingest-archive-all"


def main(
    *,
    archive_root: Path | None = None,
    parse_failure_threshold: float | None = None,
) -> int:
    """Entry point for full-archive backfill.

    Args:
        archive_root: Override path to the ScamIntelLogs checkout root.
                      When None, resolved from ``settings.phishdestroy.archive.archive_root``.
        parse_failure_threshold: Override the fraction-of-unknown-format gate.
                                  When None, resolved from settings
                                  ``phishdestroy.archive.parse_failure_rate_threshold``.

    Returns:
        0 on success; 1 on unhandled error; 2 on misconfiguration; 3 on gate failure.
    """
    from i4g.ingestion.phishdestroy.archive import ARCHIVE_ADAPTER_REGISTRY
    from i4g.ingestion.phishdestroy.archive.backfill import run_archive_backfill

    settings = get_settings()
    configure_job_logging(settings)

    archive_settings = settings.phishdestroy.archive

    # Resolve threshold.
    if parse_failure_threshold is None:
        parse_failure_threshold = archive_settings.parse_failure_rate_threshold

    # Resolve archive root.
    if archive_root is None:
        raw_root = archive_settings.archive_root
        if not raw_root:
            LOGGER.error(
                "phishdestroy.archive.archive_root is empty — set it in settings or " "pass --path on the CLI."
            )
            return 2
        archive_root = settings.project_root / raw_root if not Path(raw_root).is_absolute() else Path(raw_root)
    elif not archive_root.is_absolute():
        archive_root = settings.project_root / archive_root

    if not archive_root.is_dir():
        LOGGER.error("Archive root does not exist or is not a directory: %s", archive_root)
        return 2

    commit_sha = archive_settings.commit_sha
    if not commit_sha:
        LOGGER.error(
            "phishdestroy.archive.commit_sha is empty — set it in settings or "
            "I4G_PHISHDESTROY__ARCHIVE__COMMIT_SHA before running."
        )
        return 2

    report_dir_raw = archive_settings.report_dir
    report_dir = (
        settings.project_root / report_dir_raw if not Path(report_dir_raw).is_absolute() else Path(report_dir_raw)
    )

    LOGGER.info(
        "Starting full-archive backfill job=%s archive_root=%s commit_sha=%s threshold=%.3f",
        _INGEST_JOB,
        archive_root,
        commit_sha,
        parse_failure_threshold,
    )

    try:
        ctx = _build_archive_context(settings, archive_settings, _INGEST_JOB)
    except RuntimeError:
        LOGGER.exception("Failed to initialise stores")
        return 1

    try:
        backfill_summary = run_archive_backfill(
            archive_root=archive_root,
            ctx=ctx,
            registry=ARCHIVE_ADAPTER_REGISTRY,
            report_dir=report_dir,
        )
    except Exception:
        LOGGER.exception("Backfill run failed")
        return 1

    LOGGER.info(
        "Backfill result: %s",
        json.dumps(
            {
                "teams_attempted": backfill_summary.teams_attempted,
                "teams_ok": backfill_summary.teams_ok,
                "teams_unknown_format": backfill_summary.teams_unknown_format,
                "teams_error": backfill_summary.teams_error,
                "parse_failure_rate": backfill_summary.parse_failure_rate,
                "threshold": parse_failure_threshold,
            }
        ),
    )

    if backfill_summary.parse_failure_rate > parse_failure_threshold:
        LOGGER.error(
            "Parse-failure rate %.3f exceeds threshold %.3f — exiting 3",
            backfill_summary.parse_failure_rate,
            parse_failure_threshold,
        )
        return 3

    return 0
