"""Archive ingestion runner for PhishDestroy ScamIntelLogs team directories.

Orchestrates format detection → adapter dispatch → report file write → summary.
Catches ``UnknownFormatError`` and writes an ``unknown_format`` report rather than
propagating the exception, so the caller (CLI / worker) can continue to the next team.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from i4g.ingestion.phishdestroy.archive.detector import TeamFormat, detect_team_format

if TYPE_CHECKING:
    from i4g.ingestion.phishdestroy.archive.base import ArchiveContext, TeamAdapter

LOGGER = logging.getLogger("i4g.ingestion.phishdestroy.archive.runner")


# Default registry: maps team name → adapter class.  Import lazily to keep
# this module importable without heavy dependencies at definition time.
def _default_registry() -> dict[str, type[TeamAdapter]]:
    from i4g.ingestion.phishdestroy.archive.trustwalletpanel import TrustWalletPanelAdapter

    return {TrustWalletPanelAdapter.team_name: TrustWalletPanelAdapter}


@dataclass
class IngestArchiveSummary:
    """Summary of a single-team archive ingestion run."""

    team: str
    team_dir: Path
    format: TeamFormat
    status: str  # "ok" | "unknown_format" | "error"
    commit_sha: str
    ingested_at: str
    counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _write_report(report_dir: Path, team: str, payload: dict[str, Any]) -> None:
    """Write the per-team JSON report file to *report_dir*/<team>.json."""
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{team}.json"
    with report_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)
    LOGGER.debug("Wrote report to %s", report_path)


def ingest_team_archive(
    team_dir: Path,
    ctx: ArchiveContext,
    *,
    registry: dict[str, type[TeamAdapter]] | None = None,
    report_dir: Path | None = None,
) -> IngestArchiveSummary:
    """Orchestrate detection → adapter dispatch → report write for one team directory.

    Args:
        team_dir: Absolute path to the team directory (e.g. ``.../TrustWalletPanel``).
        ctx: Shared archive ingestion context.
        registry: Optional adapter registry overriding the default.  Defaults to
            ``{TrustWalletPanelAdapter.team_name: TrustWalletPanelAdapter}``.
        report_dir: Directory for the output JSON report file.  When None, the
            report is not written (useful in unit tests that check the return value only).

    Returns:
        ``IngestArchiveSummary`` with status, counts, warnings, and errors.

    Raises:
        FileNotFoundError: When *team_dir* does not exist at all.  The caller must
            validate the path before invoking this function.
    """
    if not team_dir.exists():
        raise FileNotFoundError(f"Team directory not found: {team_dir}")

    if registry is None:
        registry = _default_registry()

    team = team_dir.name
    ingested_at = ctx.now.strftime("%Y-%m-%dT%H:%M:%SZ")

    fmt = detect_team_format(team_dir)

    if fmt == TeamFormat.UNKNOWN:
        error_msg = "iocs.json missing or unparseable"
        LOGGER.warning("Unknown format for team=%s dir=%s: %s", team, team_dir, error_msg)

        summary = IngestArchiveSummary(
            team=team,
            team_dir=team_dir,
            format=fmt,
            status="unknown_format",
            commit_sha=ctx.commit_sha,
            ingested_at=ingested_at,
            counts={
                "chat_sessions_inserted": 0,
                "chat_sessions_updated": 0,
                "chat_sessions_unchanged": 0,
                "infrastructure_profiles_inserted": 0,
                "infrastructure_profiles_updated": 0,
                "infrastructure_profiles_unchanged": 0,
            },
            errors=[error_msg],
        )
        if report_dir is not None:
            _write_report(report_dir, team, _summary_to_report(summary))
        return summary

    # Format is SCAMINTELLOGS_V1 — look up adapter by team name.
    import json as _json

    try:
        with (team_dir / "iocs.json").open(encoding="utf-8") as fh:
            iocs_data = _json.load(fh)
        iocs_team: str = iocs_data.get("team", team)
    except Exception:
        iocs_team = team

    adapter_cls = registry.get(iocs_team)
    if adapter_cls is None and fmt == TeamFormat.FLAT_FILES:
        adapter_cls = registry.get(TeamFormat.FLAT_FILES)
    if adapter_cls is None:
        # Known format but no adapter registered for this team.
        error_msg = f"No adapter registered for team={iocs_team!r} (format={fmt.value})"
        LOGGER.warning(error_msg)
        summary = IngestArchiveSummary(
            team=iocs_team,
            team_dir=team_dir,
            format=fmt,
            status="unknown_format",
            commit_sha=ctx.commit_sha,
            ingested_at=ingested_at,
            counts={
                "chat_sessions_inserted": 0,
                "chat_sessions_updated": 0,
                "chat_sessions_unchanged": 0,
                "infrastructure_profiles_inserted": 0,
                "infrastructure_profiles_updated": 0,
                "infrastructure_profiles_unchanged": 0,
            },
            errors=[error_msg],
        )
        if report_dir is not None:
            _write_report(report_dir, iocs_team, _summary_to_report(summary))
        return summary

    adapter = adapter_cls()
    try:
        counts = adapter.ingest(team_dir, ctx)
    except Exception as exc:
        error_msg = f"Adapter {adapter_cls.__name__} raised: {exc}"
        LOGGER.exception("Archive adapter failed for team=%s", iocs_team)
        summary = IngestArchiveSummary(
            team=iocs_team,
            team_dir=team_dir,
            format=fmt,
            status="error",
            commit_sha=ctx.commit_sha,
            ingested_at=ingested_at,
            counts={
                "chat_sessions_inserted": 0,
                "chat_sessions_updated": 0,
                "chat_sessions_unchanged": 0,
                "infrastructure_profiles_inserted": 0,
                "infrastructure_profiles_updated": 0,
                "infrastructure_profiles_unchanged": 0,
            },
            errors=[error_msg],
        )
        if report_dir is not None:
            _write_report(report_dir, iocs_team, _summary_to_report(summary))
        return summary

    summary = IngestArchiveSummary(
        team=iocs_team,
        team_dir=team_dir,
        format=fmt,
        status="ok",
        commit_sha=ctx.commit_sha,
        ingested_at=ingested_at,
        counts=counts,
    )
    if report_dir is not None:
        _write_report(report_dir, iocs_team, _summary_to_report(summary))

    LOGGER.info(
        "Archive ingestion complete team=%s status=%s counts=%s",
        iocs_team,
        summary.status,
        json.dumps(counts),
    )
    return summary


def _summary_to_report(summary: IngestArchiveSummary) -> dict[str, Any]:
    """Convert an ``IngestArchiveSummary`` to the JSON report schema dict."""
    return {
        "team": summary.team,
        "team_dir": str(summary.team_dir),
        "format": summary.format.value,
        "status": summary.status,
        "commit_sha": summary.commit_sha,
        "ingested_at": summary.ingested_at,
        "counts": summary.counts,
        "warnings": summary.warnings,
        "errors": summary.errors,
    }
