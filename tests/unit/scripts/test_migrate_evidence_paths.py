"""Unit tests for migrate_evidence_paths script."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _add_scripts_to_path():
    """Make the scripts directory importable."""
    scripts_dir = str(Path(__file__).resolve().parent.parent.parent.parent / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    yield
    if scripts_dir in sys.path:
        sys.path.remove(scripts_dir)


class TestIsAlreadySharded:
    """Tests for the _is_already_sharded helper."""

    def test_sharded_path_detected(self):
        from migrate_evidence_paths import _is_already_sharded

        path = "/data/evidence/scans/fd/70/fd70a83f-91de-4533-9506-ebe3916dbff9"
        assert _is_already_sharded(path) is True

    def test_flat_path_not_sharded(self):
        from migrate_evidence_paths import _is_already_sharded

        path = "/data/evidence/fd70a83f-91de-4533-9506-ebe3916dbff9"
        assert _is_already_sharded(path) is False

    def test_gcs_sharded_uri(self):
        from migrate_evidence_paths import _is_already_sharded

        path = "gs://bucket/prefix/scans/fd/70/fd70a83f-91de-4533-9506-ebe3916dbff9"
        assert _is_already_sharded(path) is True

    def test_gcs_flat_uri(self):
        from migrate_evidence_paths import _is_already_sharded

        path = "gs://bucket/prefix/fd70a83f-91de-4533-9506-ebe3916dbff9"
        assert _is_already_sharded(path) is False


class TestMigrateLocal:
    """Tests for local filesystem migration."""

    def test_skips_already_sharded(self):
        from migrate_evidence_paths import _migrate_local

        rows = [
            {
                "scan_id": "fd70a83f-91de-4533-9506-ebe3916dbff9",
                "evidence_path": "/data/evidence/scans/fd/70/fd70a83f-91de-4533-9506-ebe3916dbff9",
            }
        ]
        settings = MagicMock()
        settings.data_dir = "/data"
        migrated, skipped, errored = _migrate_local(rows, settings=settings, dry_run=True)
        assert skipped == 1
        assert migrated == 0
        assert errored == 0

    def test_dry_run_reports_moves(self, tmp_path: Path):
        from migrate_evidence_paths import _migrate_local

        scan_id = "fd70a83f-91de-4533-9506-ebe3916dbff9"
        evidence_dir = tmp_path / "evidence" / scan_id
        evidence_dir.mkdir(parents=True)
        (evidence_dir / "report.pdf").write_text("test")

        rows = [{"scan_id": scan_id, "evidence_path": str(evidence_dir)}]
        settings = MagicMock()
        settings.data_dir = str(tmp_path)

        migrated, skipped, errored = _migrate_local(rows, settings=settings, dry_run=True)
        assert migrated == 1
        assert skipped == 0
        assert errored == 0
        # Original should still exist (dry run)
        assert evidence_dir.exists()

    @patch("migrate_evidence_paths.session_factory")
    def test_live_moves_files(self, mock_sf, tmp_path: Path):
        from migrate_evidence_paths import _migrate_local

        scan_id = "fd70a83f-91de-4533-9506-ebe3916dbff9"
        evidence_dir = tmp_path / "evidence" / scan_id
        evidence_dir.mkdir(parents=True)
        (evidence_dir / "report.pdf").write_text("test")

        rows = [{"scan_id": scan_id, "evidence_path": str(evidence_dir)}]
        settings = MagicMock()
        settings.data_dir = str(tmp_path)

        mock_session = MagicMock()
        mock_sf.return_value = MagicMock(return_value=mock_session)
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        migrated, skipped, errored = _migrate_local(rows, settings=settings, dry_run=False)
        assert migrated == 1
        assert skipped == 0
        assert errored == 0
        # Old path should not exist after move
        assert not evidence_dir.exists()
        # New sharded path should exist
        expected = tmp_path / "evidence" / "scans" / "fd" / "70" / scan_id
        assert expected.exists()
        assert (expected / "report.pdf").read_text() == "test"

    def test_skips_missing_source(self):
        from migrate_evidence_paths import _migrate_local

        rows = [
            {
                "scan_id": "fd70a83f-91de-4533-9506-ebe3916dbff9",
                "evidence_path": "/nonexistent/path/fd70a83f-91de-4533-9506-ebe3916dbff9",
            }
        ]
        settings = MagicMock()
        settings.data_dir = "/data"
        migrated, skipped, errored = _migrate_local(rows, settings=settings, dry_run=False)
        assert skipped == 1
        assert migrated == 0
