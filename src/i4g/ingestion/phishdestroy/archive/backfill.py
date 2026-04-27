"""Backfill driver for the PhishDestroy ScamIntelLogs archive (Sprint 2 Phase D).

Iterates over all team subdirectories in an archive root, calls
``ingest_team_archive`` for each, and produces an
``ArchiveBackfillSummary`` aggregating per-team results.

This module contains *only* orchestration logic — no store or settings access.
The caller (``phishdestroy_archive_all.py`` worker job) is responsible for
resolving settings and building the ``ArchiveContext``.

References:
    - Phase D manifest §"§6 Backfill driver".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from i4g.ingestion.phishdestroy.archive.base import ArchiveContext, TeamAdapter
    from i4g.ingestion.phishdestroy.archive.runner import IngestArchiveSummary

LOGGER = logging.getLogger("i4g.ingestion.phishdestroy.archive.backfill")


@dataclass
class ArchiveBackfillSummary:
    """Aggregated result of a full-archive backfill run."""

    archive_root: Path
    """Root directory scanned for team subdirectories."""

    teams_attempted: int = 0
    """Total number of team directories processed."""

    teams_ok: int = 0
    """Teams that completed with ``status == "ok"``."""

    teams_unknown_format: int = 0
    """Teams that resolved to ``status == "unknown_format"`` (skipped, not retried)."""

    teams_error: int = 0
    """Teams that produced an unhandled adapter error."""

    parse_failure_rate: float = 0.0
    """Fraction of teams with ``status == "unknown_format"`` over total attempted.

    Computed after the run completes.  When this exceeds the configured threshold
    the worker exits with code 3.
    """

    team_summaries: list[IngestArchiveSummary] = field(default_factory=list)
    """One :class:`IngestArchiveSummary` per team directory processed."""


def run_archive_backfill(
    archive_root: Path,
    ctx: ArchiveContext,
    *,
    registry: dict[str, type[TeamAdapter]] | None = None,
    report_dir: Path | None = None,
) -> ArchiveBackfillSummary:
    """Run the full-archive backfill, iterating over all team subdirectories.

    Directories that are not subdirectories (files) are silently skipped.
    For each team directory ``ingest_team_archive`` is called; exceptions are
    caught and recorded as ``status="error"`` so the loop continues.

    Args:
        archive_root: Root directory of the ScamIntelLogs checkout.
        ctx: Shared archive ingestion context (stores, provenance).
        registry: Optional adapter registry override.  Defaults to production registry.
        report_dir: Directory for per-team JSON report files.  When None, reports
            are not written (useful in tests).

    Returns:
        An :class:`ArchiveBackfillSummary` with aggregate statistics.
    """
    from i4g.ingestion.phishdestroy.archive.runner import ingest_team_archive

    if registry is None:
        from i4g.ingestion.phishdestroy.archive import ARCHIVE_ADAPTER_REGISTRY

        registry = ARCHIVE_ADAPTER_REGISTRY

    result = ArchiveBackfillSummary(archive_root=archive_root)

    team_dirs = sorted(d for d in archive_root.iterdir() if d.is_dir())
    LOGGER.info("Backfill starting: archive_root=%s total_team_dirs=%d", archive_root, len(team_dirs))

    for team_dir in team_dirs:
        result.teams_attempted += 1
        try:
            summary = ingest_team_archive(
                team_dir=team_dir,
                ctx=ctx,
                registry=registry,
                report_dir=report_dir,
            )
        except FileNotFoundError:
            LOGGER.error("Team directory vanished during scan: %s", team_dir)
            result.teams_error += 1
            continue
        except Exception:
            LOGGER.exception("Unhandled exception ingesting team_dir=%s", team_dir)
            result.teams_error += 1
            continue

        result.team_summaries.append(summary)

        if summary.status == "ok":
            result.teams_ok += 1
        elif summary.status == "unknown_format":
            result.teams_unknown_format += 1
        else:
            result.teams_error += 1

    if result.teams_attempted > 0:
        result.parse_failure_rate = result.teams_unknown_format / result.teams_attempted
    else:
        result.parse_failure_rate = 0.0

    LOGGER.info(
        "Backfill complete: attempted=%d ok=%d unknown_format=%d error=%d parse_failure_rate=%.3f",
        result.teams_attempted,
        result.teams_ok,
        result.teams_unknown_format,
        result.teams_error,
        result.parse_failure_rate,
    )
    return result
