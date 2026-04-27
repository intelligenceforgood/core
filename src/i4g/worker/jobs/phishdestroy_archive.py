"""Cloud Run / CLI entry point for the PhishDestroy ScamIntelLogs archive ingestion job."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from i4g.settings import get_settings
from i4g.worker.logging import configure_job_logging

if TYPE_CHECKING:
    from i4g.ingestion.phishdestroy.archive.base import ArchiveContext
    from i4g.settings.sections.jobs import PhishDestroyArchiveSettings

LOGGER = logging.getLogger("i4g.worker.jobs.phishdestroy_archive")

_INGEST_JOB = "i4g-jobs-ingest-archive"


def _build_archive_context(
    settings: object,
    archive_settings: PhishDestroyArchiveSettings,
    ingest_job: str,
) -> ArchiveContext:
    """Build and return an :class:`ArchiveContext` from settings.

    Extracted so both the single-team runner and the backfill driver can share
    exactly the same context-construction path without duplication.

    Args:
        settings: The resolved ``I4GSettings`` instance.
        archive_settings: The ``settings.phishdestroy.archive`` sub-section.
        ingest_job: Job identifier string embedded in provenance (e.g.
            ``"i4g-jobs-ingest-archive"`` or ``"i4g-jobs-ingest-archive-all"``).

    Returns:
        A fully initialised ``ArchiveContext``.

    Raises:
        RuntimeError: When store initialisation fails.
    """
    from i4g.ingestion.phishdestroy.archive.base import ArchiveContext
    from i4g.services.factories import (
        build_brand_impersonation_store,
        build_chat_session_store,
        build_evidence_storage,
        build_financial_damage_store,
        build_infrastructure_profile_store,
        build_threat_campaign_store,
    )

    ingest_job_run_id: str | None = os.getenv("CLOUD_RUN_EXECUTION") or None

    try:
        campaign_store = build_threat_campaign_store()
        chat_session_store = build_chat_session_store()
        infrastructure_profile_store = build_infrastructure_profile_store()
        financial_damage_store = build_financial_damage_store()
        brand_impersonation_store = build_brand_impersonation_store()
    except Exception as exc:
        raise RuntimeError("Failed to initialise stores") from exc

    evidence_storage = None
    if archive_settings.evidence_enabled:
        override = archive_settings.evidence_local_dir_override
        local_dir: Path | None = None
        if override:
            override_path = Path(override)
            local_dir = override_path if override_path.is_absolute() else settings.project_root / override_path
        try:
            evidence_storage = build_evidence_storage(local_dir=local_dir)
        except Exception:
            LOGGER.exception("Failed to initialise evidence storage; continuing without blob persistence")
            evidence_storage = None

    backend_label = "disabled" if evidence_storage is None else getattr(evidence_storage, "_backend", "unknown")
    LOGGER.info("evidence_storage_backend=%s", backend_label)

    return ArchiveContext(
        commit_sha=archive_settings.commit_sha,
        ingest_job=ingest_job,
        ingest_job_run_id=ingest_job_run_id,
        now=datetime.now(UTC),
        campaign_store=campaign_store,
        chat_session_store=chat_session_store,
        infrastructure_profile_store=infrastructure_profile_store,
        financial_damage_store=financial_damage_store,
        brand_impersonation_store=brand_impersonation_store,
        evidence_storage=evidence_storage,
    )


def main(*, team: str, archive_root: Path | None = None) -> int:
    """Entry point executed by the Cloud Run job container or CLI.

    Args:
        team: Team directory name, e.g. ``"TrustWalletPanel"``.
        archive_root: Override path to the ScamIntelLogs checkout root.
                      When None, resolved from settings.

    Returns:
        0 on success; 1 on unhandled error; 2 on misconfiguration.
    """
    from i4g.ingestion.phishdestroy.archive import ARCHIVE_ADAPTER_REGISTRY, ingest_team_archive

    settings = get_settings()
    configure_job_logging(settings)

    # Resolve archive_root from settings if not provided via CLI override.
    archive_settings = settings.phishdestroy.archive
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

    team_dir = archive_root / team
    if not team_dir.exists():
        LOGGER.error("Team directory not found: %s", team_dir)
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
        "Starting archive ingestion job=%s team=%s commit_sha=%s team_dir=%s",
        _INGEST_JOB,
        team,
        commit_sha,
        team_dir,
    )

    try:
        ctx = _build_archive_context(settings, archive_settings, _INGEST_JOB)
    except RuntimeError:
        LOGGER.exception("Failed to initialise stores")
        return 1

    try:
        summary = ingest_team_archive(
            team_dir=team_dir,
            ctx=ctx,
            registry=ARCHIVE_ADAPTER_REGISTRY,
            report_dir=report_dir,
        )
    except Exception:
        LOGGER.exception("Archive ingestion failed for team=%s", team)
        return 1

    LOGGER.info(
        "Archive ingestion result: %s",
        json.dumps(
            {
                "team": summary.team,
                "status": summary.status,
                "counts": summary.counts,
                "warnings": summary.warnings,
                "errors": summary.errors,
            }
        ),
    )

    # Return non-zero only if this single-team run failed completely.
    return 0 if summary.status in ("ok",) else 1
