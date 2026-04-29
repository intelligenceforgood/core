"""Tests for flat_files_adapter.py."""

from datetime import UTC, datetime
from pathlib import Path

from i4g.ingestion.phishdestroy.archive.base import ArchiveContext
from i4g.ingestion.phishdestroy.archive.flat_files_adapter import FlatFilesAdapter


class MockStore:
    """Mock store."""


def test_flat_files_adapter_ingest(tmp_path: Path) -> None:
    """Test flat files adapter."""
    team_dir = tmp_path / "team"
    team_dir.mkdir()
    (team_dir / "domains.txt").write_text("example.com\nexample.org\n")

    ctx = ArchiveContext(
        commit_sha="abcd123",
        ingest_job="test_job",
        ingest_job_run_id=None,
        now=datetime.now(UTC),
        campaign_store=MockStore(),  # type: ignore
        chat_session_store=MockStore(),  # type: ignore
        infrastructure_profile_store=MockStore(),  # type: ignore
        financial_damage_store=MockStore(),  # type: ignore
        brand_impersonation_store=MockStore(),  # type: ignore
        evidence_storage=None,
    )

    adapter = FlatFilesAdapter()
    counts = adapter.ingest(team_dir, ctx)
    assert counts["infrastructure_profiles_inserted"] == 2
