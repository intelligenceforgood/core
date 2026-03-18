"""Cloud Run job entrypoint for automated data retention purge.

Implements the two-phase purge strategy:
1. Soft-delete resolved cases older than ``storage.retention_days``.
2. Hard-purge soft-deleted cases older than ``storage.retention_grace_days``.

Phase 2 cascades deletion to evidence files and vector embeddings.

Usage::

    i4g jobs retention-purge          # full run
    i4g jobs retention-purge --dry-run  # preview without modifying data
"""

from __future__ import annotations

import logging
import sys

from i4g.services.factories import (
    build_evidence_storage,
    build_vector_store,
)
from i4g.services.retention import RetentionService
from i4g.settings import get_settings
from i4g.store.sql import session_factory as build_sql_session_factory
from i4g.worker.logging import configure_job_logging

LOGGER = logging.getLogger("i4g.worker.jobs.retention_purge")


def main(*, dry_run: bool = False) -> int:
    """Entry point executed by the Cloud Run job container or CLI."""

    settings = get_settings()
    configure_job_logging(settings)

    if not settings.storage.retention_enabled:
        LOGGER.info("Retention purge is disabled (I4G_STORAGE__RETENTION_ENABLED=false). Exiting.")
        return 0

    retention_days = settings.storage.retention_days
    grace_days = settings.storage.retention_grace_days

    LOGGER.info(
        "Starting retention purge: retention_days=%d, grace_days=%d, dry_run=%s",
        retention_days,
        grace_days,
        dry_run,
    )

    sf = build_sql_session_factory()

    # Build optional stores — failures are non-fatal (purge continues without them)
    evidence_storage = None
    try:
        evidence_storage = build_evidence_storage()
    except Exception:
        LOGGER.warning("Could not build evidence storage — evidence cleanup will be skipped")

    vector_store = None
    try:
        vector_store = build_vector_store()
    except Exception:
        LOGGER.warning("Could not build vector store — vector cleanup will be skipped")

    service = RetentionService(
        sf,
        evidence_storage=evidence_storage,
        vector_store=vector_store,
    )

    # Phase 1: Soft-delete
    if dry_run:
        LOGGER.info("[DRY RUN] Would soft-delete resolved cases older than %d days", retention_days)
        soft_deleted = []
    else:
        soft_deleted = service.soft_delete_expired_cases(retention_days)
        LOGGER.info("Phase 1 complete: %d cases soft-deleted", len(soft_deleted))

    # Phase 2: Hard-purge
    if dry_run:
        LOGGER.info("[DRY RUN] Would hard-purge soft-deleted cases older than %d grace days", grace_days)
        hard_purged = []
    else:
        hard_purged = service.hard_purge_deleted_cases(grace_days)
        LOGGER.info("Phase 2 complete: %d cases hard-purged", len(hard_purged))

    LOGGER.info(
        "Retention purge finished: soft_deleted=%d, hard_purged=%d",
        len(soft_deleted),
        len(hard_purged),
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
