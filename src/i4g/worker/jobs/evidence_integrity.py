"""Cloud Run job entrypoint for evidence integrity verification (WS-7: F47).

Verifies that stored evidence files match their recorded SHA-256 hashes.
Optionally backfills missing hashes before running the check.

Usage::

    i4g jobs evidence-integrity                  # full check
    i4g jobs evidence-integrity --backfill       # backfill hashes then check
    i4g jobs evidence-integrity --limit 100      # check first 100 documents
"""

from __future__ import annotations

import json
import logging

from i4g.services.evidence_integrity import EvidenceIntegrityService
from i4g.services.factories import build_evidence_storage
from i4g.settings import get_settings
from i4g.store.sql import session_factory as build_sql_session_factory
from i4g.worker.logging import configure_job_logging

LOGGER = logging.getLogger("i4g.worker.jobs.evidence_integrity")


def main(*, backfill: bool = False, limit: int | None = None) -> int:
    """Entry point executed by the Cloud Run job container or CLI."""

    settings = get_settings()
    configure_job_logging(settings)

    LOGGER.info(
        "Starting evidence integrity check: backfill=%s, limit=%s",
        backfill,
        limit,
    )

    sf = build_sql_session_factory()

    try:
        evidence_storage = build_evidence_storage()
    except Exception:
        LOGGER.error("Could not build evidence storage — aborting integrity check")
        return 1

    service = EvidenceIntegrityService(sf, evidence_storage)

    if backfill:
        count = service.backfill_hashes()
        LOGGER.info("Backfilled %d file hashes", count)

    report = service.check_all(limit=limit)

    LOGGER.info("Integrity report: %s", json.dumps(report.summary()))

    if report.mismatches > 0:
        LOGGER.error(
            "INTEGRITY FAILURE: %d files have hash mismatches",
            report.mismatches,
        )
        for r in report.results:
            if r.status == "mismatch":
                LOGGER.error(
                    "  MISMATCH doc=%s case=%s expected=%s actual=%s",
                    r.document_id,
                    r.case_id,
                    r.expected_sha256,
                    r.actual_sha256,
                )
        return 2

    return 0
