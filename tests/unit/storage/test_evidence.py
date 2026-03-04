"""Tests for i4g.storage.evidence — evidence attachment persistence."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from i4g.storage.evidence import EvidenceStorage, StoredAttachment

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _mock_settings(*, evidence_bucket: str | None = None, evidence_local_dir: str = "/tmp/evidence"):
    """Build a fake settings object."""
    return SimpleNamespace(
        storage=SimpleNamespace(
            evidence_bucket=evidence_bucket,
            evidence_local_dir=evidence_local_dir,
        ),
        secrets=SimpleNamespace(project="test-project"),
        runtime=SimpleNamespace(fallback_dir=Path("/tmp/fallback")),
    )


# ---------------------------------------------------------------------------
# Local backend tests
# ---------------------------------------------------------------------------


class TestEvidenceStorageLocal:
    def test_save_creates_file(self, tmp_path):
        settings = _mock_settings(evidence_local_dir=str(tmp_path / "evidence"))
        with patch("i4g.storage.evidence.get_settings", return_value=settings):
            store = EvidenceStorage()
            result = store.save("intake-001", "report.pdf", b"PDF content", "application/pdf")

        assert isinstance(result, StoredAttachment)
        assert result.file_name == "report.pdf"
        assert result.content_type == "application/pdf"
        assert result.size_bytes == len(b"PDF content")
        assert result.backend == "local"

        # Verify file was written
        written = Path(result.storage_uri)
        assert written.exists()
        assert written.read_bytes() == b"PDF content"

    def test_save_computes_sha256(self, tmp_path):
        data = b"test data for hashing"
        expected_checksum = hashlib.sha256(data).hexdigest()
        settings = _mock_settings(evidence_local_dir=str(tmp_path / "evidence"))
        with patch("i4g.storage.evidence.get_settings", return_value=settings):
            store = EvidenceStorage()
            result = store.save("intake-002", "data.bin", data, None)

        assert result.checksum_sha256 == expected_checksum

    def test_save_sanitizes_filename(self, tmp_path):
        settings = _mock_settings(evidence_local_dir=str(tmp_path / "evidence"))
        with patch("i4g.storage.evidence.get_settings", return_value=settings):
            store = EvidenceStorage()
            result = store.save("intake-003", "/etc/passwd/../evil.txt", b"data", None)

        assert result.file_name == "evil.txt"  # os.path.basename strips path

    def test_save_empty_filename_uses_default(self, tmp_path):
        settings = _mock_settings(evidence_local_dir=str(tmp_path / "evidence"))
        with patch("i4g.storage.evidence.get_settings", return_value=settings):
            store = EvidenceStorage()
            result = store.save("intake-004", "", b"data", None)

        assert result.file_name == "uploaded_evidence"

    def test_local_dir_created_automatically(self, tmp_path):
        new_dir = tmp_path / "deep" / "nested" / "evidence"
        settings = _mock_settings(evidence_local_dir=str(new_dir))
        with patch("i4g.storage.evidence.get_settings", return_value=settings):
            store = EvidenceStorage()
            store.save("intake-005", "file.txt", b"hello", None)

        assert new_dir.exists()

    def test_attachment_id_is_deterministic(self, tmp_path):
        data = b"same data"
        settings = _mock_settings(evidence_local_dir=str(tmp_path / "evidence"))
        with patch("i4g.storage.evidence.get_settings", return_value=settings):
            store = EvidenceStorage()
            r1 = store.save("intake-006", "file.txt", data, None)
            r2 = store.save("intake-006", "file.txt", data, None)

        assert r1.attachment_id == r2.attachment_id


# ---------------------------------------------------------------------------
# GCS backend tests (mocked)
# ---------------------------------------------------------------------------


class TestEvidenceStorageGCS:
    @patch("i4g.storage.evidence.storage")
    def test_save_uploads_to_gcs(self, mock_gcs_module, tmp_path):
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()

        mock_gcs_module.Client.return_value = mock_client
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        settings = _mock_settings(evidence_bucket="my-bucket")
        with patch("i4g.storage.evidence.get_settings", return_value=settings):
            store = EvidenceStorage()
            result = store.save("intake-010", "doc.pdf", b"gcs data", "application/pdf")

        assert result.backend == "gcs"
        assert result.storage_uri.startswith("gs://my-bucket/")
        mock_blob.upload_from_file.assert_called_once()
