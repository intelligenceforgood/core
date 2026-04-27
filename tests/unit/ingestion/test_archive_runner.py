"""Tests for the PhishDestroy archive runner (format detection + dispatch + report)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from i4g.ingestion.phishdestroy.archive.base import ArchiveContext
from i4g.ingestion.phishdestroy.archive.detector import TeamFormat
from i4g.ingestion.phishdestroy.archive.runner import ingest_team_archive
from i4g.store.brand_impersonation_store import BrandImpersonationStore
from i4g.store.chat_session_store import ChatSessionStore
from i4g.store.financial_damage_store import FinancialDamageStore
from i4g.store.infrastructure_profile_store import InfrastructureProfileStore
from i4g.store.threat_campaign_store import ThreatCampaignStore

_PINNED_SHA = "83d0307420fcc865fcb8a34b8c454acbc6d56f1f"
_INGEST_JOB = "test-ingest-archive"
_NOW = datetime(2026, 4, 27, 15, 30, 0, tzinfo=UTC)


def _make_ctx(tmp_path: Path) -> ArchiveContext:
    """Build an ArchiveContext backed by in-memory SQLite stores."""
    db = tmp_path / "test.db"
    return ArchiveContext(
        commit_sha=_PINNED_SHA,
        ingest_job=_INGEST_JOB,
        ingest_job_run_id=None,
        now=_NOW,
        campaign_store=ThreatCampaignStore(db_path=str(db)),
        chat_session_store=ChatSessionStore(db_path=str(db)),
        infrastructure_profile_store=InfrastructureProfileStore(db_path=str(db)),
        financial_damage_store=FinancialDamageStore(db_path=str(db)),
        brand_impersonation_store=BrandImpersonationStore(db_path=str(db)),
    )


class TestUnknownFormatDirectory:
    """Runner handles a directory with no iocs.json gracefully."""

    def test_missing_iocs_writes_unknown_format_report(self, tmp_path: Path) -> None:
        """Unknown-format directory → report status=unknown_format, zero rows written."""
        team_dir = tmp_path / "GhostTeam"
        team_dir.mkdir()
        report_dir = tmp_path / "reports"
        ctx = _make_ctx(tmp_path)

        summary = ingest_team_archive(team_dir, ctx, report_dir=report_dir)

        assert summary.status == "unknown_format"
        assert summary.format == TeamFormat.UNKNOWN
        assert all(v == 0 for v in summary.counts.values())
        assert summary.errors

        # Report file must exist.
        report_path = report_dir / "GhostTeam.json"
        assert report_path.exists()
        report = json.loads(report_path.read_text())
        assert report["status"] == "unknown_format"
        assert report["counts"]["chat_sessions_inserted"] == 0

    def test_unknown_format_does_not_raise(self, tmp_path: Path) -> None:
        """The runner must not propagate exceptions for unknown-format directories."""
        team_dir = tmp_path / "SilentTeam"
        team_dir.mkdir()
        ctx = _make_ctx(tmp_path)

        # Should not raise.
        summary = ingest_team_archive(team_dir, ctx)
        assert summary.status == "unknown_format"


class TestMissingTeamDirectory:
    """Runner raises FileNotFoundError when the team directory doesn't exist at all."""

    def test_missing_directory_raises_file_not_found(self, tmp_path: Path) -> None:
        """A path that doesn't exist at all raises FileNotFoundError."""
        team_dir = tmp_path / "NonExistentTeam"
        ctx = _make_ctx(tmp_path)

        with pytest.raises(FileNotFoundError):
            ingest_team_archive(team_dir, ctx)


class TestUnregisteredTeamInKnownFormat:
    """Known-format directory with no matching adapter → unknown_format report, no crash."""

    def test_unregistered_team_writes_unknown_format_report(self, tmp_path: Path) -> None:
        """Known format but no adapter in registry → unknown_format, no exception."""
        team_dir = tmp_path / "FutureTeam"
        team_dir.mkdir()
        (team_dir / "iocs.json").write_text(
            json.dumps({"team": "FutureTeam", "panel_url": "future.example.com"}),
            encoding="utf-8",
        )
        report_dir = tmp_path / "reports"
        ctx = _make_ctx(tmp_path)

        # Pass an empty registry so no adapter is found.
        summary = ingest_team_archive(team_dir, ctx, registry={}, report_dir=report_dir)

        assert summary.status == "unknown_format"
        assert all(v == 0 for v in summary.counts.values())
        assert summary.errors

        report_path = report_dir / "FutureTeam.json"
        assert report_path.exists()
