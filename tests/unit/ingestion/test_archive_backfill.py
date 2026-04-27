"""Unit tests for the archive backfill driver (Sprint 2 Phase D).

Tests verify:
- Empty archive root returns zero counts and rate=0.0.
- All-ok teams produce correct aggregate counts.
- Unknown-format teams increment teams_unknown_format.
- parse_failure_rate is computed correctly.
- Files (non-directories) in archive root are silently skipped.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from i4g.ingestion.phishdestroy.archive.backfill import run_archive_backfill
from i4g.ingestion.phishdestroy.archive.runner import IngestArchiveSummary
from i4g.store.brand_impersonation_store import BrandImpersonationStore
from i4g.store.chat_session_store import ChatSessionStore
from i4g.store.financial_damage_store import FinancialDamageStore
from i4g.store.infrastructure_profile_store import InfrastructureProfileStore
from i4g.store.threat_campaign_store import ThreatCampaignStore

_PINNED_SHA = "0000000000000000000000000000000000000001"
_NOW = datetime(2026, 4, 27, 17, 0, 0, tzinfo=UTC)


def _make_ctx(tmp_path: Path):
    from i4g.ingestion.phishdestroy.archive.base import ArchiveContext

    db = tmp_path / "test.db"
    return ArchiveContext(
        commit_sha=_PINNED_SHA,
        ingest_job="test-backfill",
        ingest_job_run_id=None,
        now=_NOW,
        campaign_store=ThreatCampaignStore(db_path=str(db)),
        chat_session_store=ChatSessionStore(db_path=str(db)),
        infrastructure_profile_store=InfrastructureProfileStore(db_path=str(db)),
        financial_damage_store=FinancialDamageStore(db_path=str(db)),
        brand_impersonation_store=BrandImpersonationStore(db_path=str(db)),
    )


def _fake_summary(team: str, team_dir: Path, status: str = "ok") -> IngestArchiveSummary:
    from i4g.ingestion.phishdestroy.archive.detector import TeamFormat

    return IngestArchiveSummary(
        team=team,
        team_dir=team_dir,
        format=TeamFormat.SCAMINTELLOGS_V1,
        status=status,
        commit_sha=_PINNED_SHA,
        ingested_at="2026-04-27T17:00:00Z",
        counts={"chat_sessions_inserted": 1},
    )


class TestRunArchiveBackfillEmpty:
    def test_empty_root_returns_zero_counts(self, tmp_path: Path) -> None:
        archive_root = tmp_path / "archive"
        archive_root.mkdir()
        ctx = _make_ctx(tmp_path)

        result = run_archive_backfill(archive_root, ctx, registry={})

        assert result.teams_attempted == 0
        assert result.teams_ok == 0
        assert result.teams_unknown_format == 0
        assert result.teams_error == 0
        assert result.parse_failure_rate == 0.0

    def test_files_in_root_are_skipped(self, tmp_path: Path) -> None:
        archive_root = tmp_path / "archive"
        archive_root.mkdir()
        (archive_root / "README.md").write_text("not a team dir")
        ctx = _make_ctx(tmp_path)

        result = run_archive_backfill(archive_root, ctx, registry={})
        assert result.teams_attempted == 0


class TestRunArchiveBackfillCounts:
    def test_all_ok_teams_counted(self, tmp_path: Path) -> None:
        archive_root = tmp_path / "archive"
        archive_root.mkdir()
        team_dirs = [archive_root / f"Team{i}" for i in range(3)]
        for d in team_dirs:
            d.mkdir()

        ctx = _make_ctx(tmp_path)

        def fake_ingest(team_dir, ctx, *, registry=None, report_dir=None):
            return _fake_summary(team_dir.name, team_dir, "ok")

        with patch(
            "i4g.ingestion.phishdestroy.archive.runner.ingest_team_archive",
            side_effect=fake_ingest,
        ):
            result = run_archive_backfill(archive_root, ctx, registry={})

        assert result.teams_attempted == 3
        assert result.teams_ok == 3
        assert result.teams_unknown_format == 0
        assert result.teams_error == 0
        assert result.parse_failure_rate == 0.0

    def test_unknown_format_teams_counted(self, tmp_path: Path) -> None:
        archive_root = tmp_path / "archive"
        archive_root.mkdir()
        (archive_root / "TeamA").mkdir()
        (archive_root / "TeamB").mkdir()

        ctx = _make_ctx(tmp_path)

        def fake_ingest(team_dir, ctx, *, registry=None, report_dir=None):
            if team_dir.name == "TeamA":
                return _fake_summary("TeamA", team_dir, "ok")
            return _fake_summary("TeamB", team_dir, "unknown_format")

        with patch(
            "i4g.ingestion.phishdestroy.archive.runner.ingest_team_archive",
            side_effect=fake_ingest,
        ):
            result = run_archive_backfill(archive_root, ctx, registry={})

        assert result.teams_unknown_format == 1
        assert result.parse_failure_rate == pytest.approx(0.5)

    def test_parse_failure_rate_within_threshold_gives_zero(self, tmp_path: Path) -> None:
        """100 ok, 0 unknown → rate = 0.0"""
        archive_root = tmp_path / "archive"
        archive_root.mkdir()
        for i in range(5):
            (archive_root / f"Team{i}").mkdir()

        ctx = _make_ctx(tmp_path)

        def fake_ingest(team_dir, ctx, *, registry=None, report_dir=None):
            return _fake_summary(team_dir.name, team_dir, "ok")

        with patch(
            "i4g.ingestion.phishdestroy.archive.runner.ingest_team_archive",
            side_effect=fake_ingest,
        ):
            result = run_archive_backfill(archive_root, ctx, registry={})

        assert result.parse_failure_rate == pytest.approx(0.0)

    def test_team_summaries_populated(self, tmp_path: Path) -> None:
        archive_root = tmp_path / "archive"
        archive_root.mkdir()
        (archive_root / "TeamX").mkdir()

        ctx = _make_ctx(tmp_path)

        def fake_ingest(team_dir, ctx, *, registry=None, report_dir=None):
            return _fake_summary("TeamX", team_dir, "ok")

        with patch(
            "i4g.ingestion.phishdestroy.archive.runner.ingest_team_archive",
            side_effect=fake_ingest,
        ):
            result = run_archive_backfill(archive_root, ctx, registry={})

        assert len(result.team_summaries) == 1
        assert result.team_summaries[0].team == "TeamX"
