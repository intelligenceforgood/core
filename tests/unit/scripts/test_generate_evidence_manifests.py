"""Unit tests for generate_evidence_manifests script."""

from __future__ import annotations

import json
import sys
from pathlib import Path

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


class TestComputeSha256:
    """Tests for _compute_sha256 helper."""

    def test_correct_hash(self, tmp_path: Path):
        from generate_evidence_manifests import _compute_sha256

        f = tmp_path / "test.txt"
        f.write_text("hello world")
        digest = _compute_sha256(f)
        assert len(digest) == 64
        assert digest == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"


class TestGenerateManifestLocal:
    """Tests for _generate_manifest_local."""

    def test_manifest_content(self, tmp_path: Path):
        from generate_evidence_manifests import _generate_manifest_local

        scan_id = "fd70a83f-91de-4533-9506-ebe3916dbff9"
        evidence_dir = tmp_path / scan_id
        evidence_dir.mkdir()
        (evidence_dir / "report.pdf").write_bytes(b"report content")
        screenshots = evidence_dir / "screenshots"
        screenshots.mkdir()
        (screenshots / "step-001.png").write_bytes(b"screenshot data")

        manifest = _generate_manifest_local(scan_id, evidence_dir)

        assert manifest["scan_id"] == scan_id
        assert manifest["file_count"] == 2
        assert "generated_at" in manifest
        paths = {f["path"] for f in manifest["files"]}
        assert "report.pdf" in paths
        assert "screenshots/step-001.png" in paths

        for f in manifest["files"]:
            assert "size_bytes" in f
            assert "sha256" in f
            assert len(f["sha256"]) == 64

    def test_excludes_existing_metadata(self, tmp_path: Path):
        from generate_evidence_manifests import _generate_manifest_local

        scan_id = "fd70a83f-91de-4533-9506-ebe3916dbff9"
        evidence_dir = tmp_path / scan_id
        evidence_dir.mkdir()
        (evidence_dir / "report.pdf").write_bytes(b"content")
        (evidence_dir / "metadata.json").write_text("{}")

        manifest = _generate_manifest_local(scan_id, evidence_dir)
        assert manifest["file_count"] == 1
        paths = {f["path"] for f in manifest["files"]}
        assert "metadata.json" not in paths


class TestProcessLocal:
    """Tests for _process_local."""

    def test_dry_run_does_not_write(self, tmp_path: Path):
        from generate_evidence_manifests import _process_local

        scan_id = "fd70a83f-91de-4533-9506-ebe3916dbff9"
        evidence_dir = tmp_path / scan_id
        evidence_dir.mkdir()
        (evidence_dir / "report.pdf").write_bytes(b"content")

        rows = [{"scan_id": scan_id, "evidence_path": str(evidence_dir)}]
        generated, skipped, errored = _process_local(rows, dry_run=True)
        assert generated == 1
        assert not (evidence_dir / "metadata.json").exists()

    def test_live_writes_manifest(self, tmp_path: Path):
        from generate_evidence_manifests import _process_local

        scan_id = "fd70a83f-91de-4533-9506-ebe3916dbff9"
        evidence_dir = tmp_path / scan_id
        evidence_dir.mkdir()
        (evidence_dir / "report.pdf").write_bytes(b"content")

        rows = [{"scan_id": scan_id, "evidence_path": str(evidence_dir)}]
        generated, skipped, errored = _process_local(rows, dry_run=False)
        assert generated == 1
        manifest_path = evidence_dir / "metadata.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text())
        assert manifest["scan_id"] == scan_id
        assert manifest["file_count"] == 1

    def test_skips_existing_manifest(self, tmp_path: Path):
        from generate_evidence_manifests import _process_local

        scan_id = "fd70a83f-91de-4533-9506-ebe3916dbff9"
        evidence_dir = tmp_path / scan_id
        evidence_dir.mkdir()
        (evidence_dir / "report.pdf").write_bytes(b"content")
        (evidence_dir / "metadata.json").write_text("{}")

        rows = [{"scan_id": scan_id, "evidence_path": str(evidence_dir)}]
        generated, skipped, errored = _process_local(rows, dry_run=False)
        assert skipped == 1
        assert generated == 0

    def test_skips_missing_dir(self):
        from generate_evidence_manifests import _process_local

        rows = [{"scan_id": "abc", "evidence_path": "/nonexistent/path"}]
        generated, skipped, errored = _process_local(rows, dry_run=False)
        assert skipped == 1

    def test_skips_gcs_paths_in_local_mode(self):
        from generate_evidence_manifests import _process_local

        rows = [{"scan_id": "abc", "evidence_path": "gs://bucket/prefix/abc"}]
        generated, skipped, errored = _process_local(rows, dry_run=False)
        assert skipped == 1
