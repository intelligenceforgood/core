"""Cloud Run / CLI entry point for the PhishDestroy destroylist ingestion job."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from i4g.services.factories import build_blocklist_hit_store
from i4g.settings import get_settings
from i4g.worker.logging import configure_job_logging

LOGGER = logging.getLogger("i4g.worker.jobs.phishdestroy_destroylist")

_INGEST_JOB = "i4g-jobs-ingest-destroylist"


def main(*, data_path: Path | None = None) -> int:
    """Entry point executed by the Cloud Run job container or CLI.

    Args:
        data_path: Override path to DestroyScammers/data/data.json.
                   When None, resolved from settings.

    Returns:
        0 on success; 1 on unhandled error; 2 on misconfiguration.
    """
    from i4g.ingestion.phishdestroy.destroylist import ingest_destroylist

    settings = get_settings()
    configure_job_logging(settings)

    ingest_job_run_id: str | None = os.getenv("CLOUD_RUN_EXECUTION") or None

    # Resolve data_path from settings if not provided via CLI override.
    if data_path is None:
        raw_path = settings.phishdestroy.destroylist.data_path
        data_path = settings.project_root / raw_path if not Path(raw_path).is_absolute() else Path(raw_path)
    else:
        data_path = settings.project_root / data_path if not data_path.is_absolute() else data_path

    commit_sha = settings.phishdestroy.destroylist.commit_sha
    if not commit_sha:
        LOGGER.error(
            "phishdestroy.destroylist.commit_sha is empty — set it in settings or "
            "I4G_PHISHDESTROY__DESTROYLIST__COMMIT_SHA before running."
        )
        return 2

    if not data_path.exists():
        LOGGER.error("destroylist data file not found: %s", data_path)
        return 2

    LOGGER.info(
        "Starting destroylist ingestion job=%s commit_sha=%s data_path=%s",
        _INGEST_JOB,
        commit_sha,
        data_path,
    )

    try:
        store = build_blocklist_hit_store()
    except Exception:
        LOGGER.exception("Failed to initialise BlocklistHitStore")
        return 1

    try:
        summary = ingest_destroylist(
            data_path=data_path,
            commit_sha=commit_sha,
            ingest_job=_INGEST_JOB,
            ingest_job_run_id=ingest_job_run_id,
            store=store,
        )
    except Exception:
        LOGGER.exception("destroylist ingestion failed")
        return 1

    LOGGER.info(
        "destroylist ingestion complete: %s",
        json.dumps(
            {
                "total_seen": summary.total_seen,
                "unique_domains": summary.unique_domains,
                "rows_inserted": summary.rows_inserted,
                "rows_updated": summary.rows_updated,
                "rows_unchanged": summary.rows_unchanged,
            }
        ),
    )
    return 0
