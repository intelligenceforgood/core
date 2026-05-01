"""Cloud Run / CLI entry point for the PhishDestroy actors ingestion job."""

from __future__ import annotations

import logging
from pathlib import Path

from i4g.services.factories import (
    build_actor_identity_edge_store,
    build_actor_identity_store,
    build_leak_record_store,
    build_registrant_pivot_store,
    build_threat_actor_store,
)
from i4g.settings import get_settings
from i4g.worker.logging import configure_job_logging

LOGGER = logging.getLogger("i4g.worker.jobs.phishdestroy_actors")

_INGEST_JOB = "i4g-jobs-ingest-phishdestroy-actors"


def main(*, data_path: Path | None = None) -> int:
    """Entry point executed by the Cloud Run job container or CLI.

    Args:
        data_path: Override path to DestroyScammers/data/data.json.
                   When None, resolved from settings.

    Returns:
        0 on success; 1 on unhandled error; 2 on misconfiguration.
    """
    from i4g.ingestion.phishdestroy.actors import ingest_actors

    configure_job_logging()

    settings = get_settings()
    data_path = data_path or settings.phishdestroy.destroylist.data_path

    # The actors data comes from the same DestroyScammers repo as the destroylist.
    commit_sha = settings.phishdestroy.destroylist.commit_sha
    if not commit_sha:
        LOGGER.error("phishdestroy.destroylist.commit_sha is empty. Set it in settings before running.")
        return 2

    if not data_path.exists():
        LOGGER.error("actors data file not found: %s", data_path)
        return 2

    LOGGER.info(
        "Starting phishdestroy actors ingestion job=%s commit_sha=%s data_path=%s",
        _INGEST_JOB,
        commit_sha,
        data_path,
    )

    try:
        threat_actor_store = build_threat_actor_store()
        actor_identity_store = build_actor_identity_store()
        leak_record_store = build_leak_record_store()
        registrant_pivot_store = build_registrant_pivot_store()
        actor_identity_edge_store = build_actor_identity_edge_store()
    except Exception:
        LOGGER.exception("Failed to initialise stores")
        return 1

    ingest_job_run_id = getattr(settings.runtime, "cloud_run_execution", None) if settings.runtime else None

    try:
        summary = ingest_actors(
            data_path=data_path,
            commit_sha=commit_sha,
            ingest_job=_INGEST_JOB,
            ingest_job_run_id=ingest_job_run_id,
            threat_actor_store=threat_actor_store,
            actor_identity_store=actor_identity_store,
            leak_record_store=leak_record_store,
            registrant_pivot_store=registrant_pivot_store,
            actor_identity_edge_store=actor_identity_edge_store,
        )
    except Exception:
        LOGGER.exception("actors ingestion failed")
        return 1

    LOGGER.info(
        "actors ingestion complete: actors=%d leaks=%d registrants=%d edges=%d",
        summary.actors_inserted + summary.actors_updated,
        summary.leaks_inserted + summary.leaks_updated,
        summary.registrants_inserted + summary.registrants_updated,
        summary.edges_inserted + summary.edges_updated,
    )
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
