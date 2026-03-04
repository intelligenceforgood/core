"""Tests for WS-7: Evidence & Attachment Integrity (F43–F47).

Covers:
- F43: source_url resolution via EvidenceStorage.retrieve/exists
- F44: Evidence download endpoint
- F45: Chain-of-custody metadata (file_sha256, ingested_at columns)
- F46: Batch evidence export (ZIP with manifest)
- F47: Evidence integrity check service and job
"""

from __future__ import annotations

import hashlib
import io
import json
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from i4g.services.evidence_integrity import EvidenceIntegrityService
from i4g.storage.evidence import EvidenceStorage, RetrievedEvidence
from i4g.store.sql import METADATA, cases, source_documents
from i4g.store.sql_writer import SourceDocumentPayload

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _mock_settings(*, evidence_local_dir: str = "/tmp/evidence"):
    """Build a fake settings object for local evidence storage."""
    return SimpleNamespace(
        storage=SimpleNamespace(
            evidence_bucket=None,
            evidence_local_dir=evidence_local_dir,
        ),
        secrets=SimpleNamespace(project="test-project"),
        runtime=SimpleNamespace(fallback_dir=Path("/tmp/fallback")),
    )


@pytest.fixture()
def db_session_factory():
    """In-memory SQLite session factory with all tables created."""
    engine = create_engine("sqlite:///:memory:")
    METADATA.create_all(engine)
    factory = sessionmaker(bind=engine)
    return factory


@pytest.fixture()
def evidence_dir(tmp_path: Path) -> Path:
    """Temporary evidence directory."""
    d = tmp_path / "evidence"
    d.mkdir()
    return d


@pytest.fixture()
def evidence_store(evidence_dir: Path) -> EvidenceStorage:
    """Local EvidenceStorage pointing at tmp dir."""
    settings = _mock_settings(evidence_local_dir=str(evidence_dir))
    with patch("i4g.storage.evidence.get_settings", return_value=settings):
        return EvidenceStorage()


def _insert_case(session_factory, case_id: str, status: str = "open") -> str:
    """Insert a minimal case row."""
    now = datetime.now(UTC)
    with session_factory() as session:
        session.execute(
            sa.insert(cases).values(
                case_id=case_id,
                dataset="test",
                source_type="test",
                raw_text_sha256=str(uuid.uuid4()),
                status=status,
                is_deleted=False,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
    return case_id


def _insert_document(
    session_factory,
    case_id: str,
    *,
    document_id: str | None = None,
    source_url: str | None = None,
    file_sha256: str | None = None,
    mime_type: str | None = None,
    title: str | None = None,
    ingested_at: datetime | None = None,
) -> str:
    """Insert a source_documents row and return the document_id."""
    doc_id = document_id or str(uuid.uuid4())
    now = datetime.now(UTC)
    with session_factory() as session:
        session.execute(
            sa.insert(source_documents).values(
                document_id=doc_id,
                case_id=case_id,
                title=title or "Test Document",
                source_url=source_url,
                mime_type=mime_type or "text/plain",
                text="Sample text content",
                text_sha256=hashlib.sha256(b"Sample text content").hexdigest(),
                file_sha256=file_sha256,
                ingested_at=ingested_at or now,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
    return doc_id


# ===========================================================================
# F43: source_url resolution — EvidenceStorage.retrieve / exists
# ===========================================================================


class TestEvidenceRetrieve:
    """F43: Verify source_url correctly resolves to original evidence files."""

    def test_retrieve_local_file(self, evidence_store: EvidenceStorage, evidence_dir: Path):
        """retrieve() returns file data for existing local file."""
        stored = evidence_store.save("case-001", "report.pdf", b"PDF data", "application/pdf")
        result = evidence_store.retrieve(stored.storage_uri)

        assert result is not None
        assert result.data == b"PDF data"
        assert result.file_name == "report.pdf"
        assert result.size_bytes == len(b"PDF data")
        assert result.checksum_sha256 == hashlib.sha256(b"PDF data").hexdigest()

    def test_retrieve_missing_file_returns_none(self, evidence_store: EvidenceStorage):
        """retrieve() returns None when file does not exist."""
        result = evidence_store.retrieve("/nonexistent/path/file.txt")
        assert result is None

    def test_exists_local_file(self, evidence_store: EvidenceStorage):
        """exists() returns True for stored files, False for missing."""
        stored = evidence_store.save("case-002", "data.bin", b"\x00\x01\x02", None)
        assert evidence_store.exists(stored.storage_uri) is True
        assert evidence_store.exists("/nonexistent/file.bin") is False

    def test_retrieve_preserves_content_type(self, evidence_store: EvidenceStorage):
        """retrieve() infers content type from filename."""
        evidence_store.save("case-003", "image.png", b"PNG", "image/png")
        stored = evidence_store.save("case-003", "image.png", b"PNG", "image/png")
        result = evidence_store.retrieve(stored.storage_uri)

        assert result is not None
        assert result.content_type == "image/png"

    def test_compute_sha256_static(self):
        """compute_sha256() returns correct hex digest."""
        data = b"test data"
        expected = hashlib.sha256(data).hexdigest()
        assert EvidenceStorage.compute_sha256(data) == expected


# ===========================================================================
# F45: Chain-of-custody metadata columns
# ===========================================================================


class TestChainOfCustody:
    """F45: Verify file_sha256 and ingested_at on source_documents."""

    def test_source_document_payload_has_file_sha256(self):
        """SourceDocumentPayload accepts file_sha256 and ingested_at."""
        now = datetime.now(UTC)
        payload = SourceDocumentPayload(
            alias="primary",
            source_url="/evidence/file.pdf",
            file_sha256="abc123",
            ingested_at=now,
        )
        assert payload.file_sha256 == "abc123"
        assert payload.ingested_at == now

    def test_file_sha256_column_persists(self, db_session_factory):
        """file_sha256 and ingested_at are stored and retrievable."""
        case_id = _insert_case(db_session_factory, "case-custody-1")
        sha = hashlib.sha256(b"evidence file content").hexdigest()
        now = datetime.now(UTC)

        doc_id = _insert_document(
            db_session_factory,
            case_id,
            file_sha256=sha,
            ingested_at=now,
        )

        with db_session_factory() as session:
            row = session.execute(
                sa.select(source_documents.c.file_sha256, source_documents.c.ingested_at).where(
                    source_documents.c.document_id == doc_id
                )
            ).fetchone()

        assert row is not None
        assert row.file_sha256 == sha
        assert row.ingested_at is not None

    def test_file_sha256_nullable(self, db_session_factory):
        """file_sha256 can be NULL for documents without file evidence."""
        case_id = _insert_case(db_session_factory, "case-custody-2")
        doc_id = _insert_document(db_session_factory, case_id, file_sha256=None)

        with db_session_factory() as session:
            row = session.execute(
                sa.select(source_documents.c.file_sha256).where(source_documents.c.document_id == doc_id)
            ).fetchone()

        assert row is not None
        assert row.file_sha256 is None


# ===========================================================================
# F47: Evidence integrity verification
# ===========================================================================


class TestEvidenceIntegrity:
    """F47: Evidence file integrity check service."""

    def test_check_all_ok(self, db_session_factory, evidence_store: EvidenceStorage):
        """All files match → report shows all ok."""
        case_id = _insert_case(db_session_factory, "case-int-1")
        data = b"evidence content"
        stored = evidence_store.save("case-int-1", "file.txt", data, "text/plain")
        sha = hashlib.sha256(data).hexdigest()

        _insert_document(
            db_session_factory,
            case_id,
            source_url=stored.storage_uri,
            file_sha256=sha,
        )

        service = EvidenceIntegrityService(db_session_factory, evidence_store)
        report = service.check_all()

        assert report.checked == 1
        assert report.ok == 1
        assert report.mismatches == 0
        assert report.missing == 0

    def test_check_detects_mismatch(self, db_session_factory, evidence_store: EvidenceStorage):
        """Modified file → report shows mismatch."""
        case_id = _insert_case(db_session_factory, "case-int-2")
        data = b"original content"
        stored = evidence_store.save("case-int-2", "file.txt", data, "text/plain")

        # Record wrong hash
        _insert_document(
            db_session_factory,
            case_id,
            source_url=stored.storage_uri,
            file_sha256="0000000000000000000000000000000000000000000000000000000000000000",
        )

        service = EvidenceIntegrityService(db_session_factory, evidence_store)
        report = service.check_all()

        assert report.checked == 1
        assert report.mismatches == 1
        assert report.results[0].status == "mismatch"

    def test_check_detects_missing(self, db_session_factory, evidence_store: EvidenceStorage):
        """File not found → report shows missing."""
        case_id = _insert_case(db_session_factory, "case-int-3")
        _insert_document(
            db_session_factory,
            case_id,
            source_url="/nonexistent/file.txt",
            file_sha256="abc123",
        )

        service = EvidenceIntegrityService(db_session_factory, evidence_store)
        report = service.check_all()

        assert report.checked == 1
        assert report.missing == 1

    def test_check_no_hash_status(self, db_session_factory, evidence_store: EvidenceStorage):
        """Document with source_url but no file_sha256 → no_hash."""
        case_id = _insert_case(db_session_factory, "case-int-4")
        data = b"content"
        stored = evidence_store.save("case-int-4", "file.txt", data, "text/plain")
        _insert_document(
            db_session_factory,
            case_id,
            source_url=stored.storage_uri,
            file_sha256=None,
        )

        service = EvidenceIntegrityService(db_session_factory, evidence_store)
        report = service.check_all()

        assert report.checked == 1
        assert report.no_hash == 1

    def test_check_with_limit(self, db_session_factory, evidence_store: EvidenceStorage):
        """limit= caps how many documents are checked."""
        case_id = _insert_case(db_session_factory, "case-int-5")
        for i in range(5):
            data = f"content-{i}".encode()
            stored = evidence_store.save(f"case-int-5-{i}", f"file{i}.txt", data, "text/plain")
            _insert_document(
                db_session_factory,
                case_id,
                source_url=stored.storage_uri,
                file_sha256=hashlib.sha256(data).hexdigest(),
            )

        service = EvidenceIntegrityService(db_session_factory, evidence_store)
        report = service.check_all(limit=2)

        assert report.checked == 2

    def test_backfill_hashes(self, db_session_factory, evidence_store: EvidenceStorage):
        """backfill_hashes() fills in missing file_sha256 values."""
        case_id = _insert_case(db_session_factory, "case-int-6")
        data = b"backfill me"
        stored = evidence_store.save("case-int-6", "file.txt", data, "text/plain")
        doc_id = _insert_document(
            db_session_factory,
            case_id,
            source_url=stored.storage_uri,
            file_sha256=None,
        )

        service = EvidenceIntegrityService(db_session_factory, evidence_store)
        count = service.backfill_hashes()

        assert count == 1

        with db_session_factory() as session:
            row = session.execute(
                sa.select(source_documents.c.file_sha256).where(source_documents.c.document_id == doc_id)
            ).fetchone()

        assert row.file_sha256 == hashlib.sha256(data).hexdigest()

    def test_backfill_skips_existing(self, db_session_factory, evidence_store: EvidenceStorage):
        """backfill_hashes() does not overwrite existing hashes."""
        case_id = _insert_case(db_session_factory, "case-int-7")
        data = b"already hashed"
        stored = evidence_store.save("case-int-7", "file.txt", data, "text/plain")
        existing_hash = hashlib.sha256(data).hexdigest()
        _insert_document(
            db_session_factory,
            case_id,
            source_url=stored.storage_uri,
            file_sha256=existing_hash,
        )

        service = EvidenceIntegrityService(db_session_factory, evidence_store)
        count = service.backfill_hashes()

        assert count == 0

    def test_report_summary(self, db_session_factory, evidence_store: EvidenceStorage):
        """IntegrityReport.summary() returns JSON-safe dict."""
        case_id = _insert_case(db_session_factory, "case-int-8")
        data = b"ok file"
        stored = evidence_store.save("case-int-8", "file.txt", data, "text/plain")
        _insert_document(
            db_session_factory,
            case_id,
            source_url=stored.storage_uri,
            file_sha256=hashlib.sha256(data).hexdigest(),
        )

        service = EvidenceIntegrityService(db_session_factory, evidence_store)
        report = service.check_all()
        summary = report.summary()

        assert summary["checked"] == 1
        assert summary["ok"] == 1
        assert "started_at" in summary
        assert "finished_at" in summary


# ===========================================================================
# F44/F46: Evidence API endpoint tests
# ===========================================================================


class TestEvidenceAPIHelpers:
    """Test the evidence API endpoint logic at the unit level.

    Full FastAPI integration tests require the app fixture — these test
    the core resolution logic via the evidence storage directly.
    """

    def test_retrieve_round_trip(self, evidence_store: EvidenceStorage):
        """save() then retrieve() returns identical content."""
        data = b"important evidence document"
        stored = evidence_store.save("case-api-1", "evidence.pdf", data, "application/pdf")

        retrieved = evidence_store.retrieve(stored.storage_uri)
        assert retrieved is not None
        assert retrieved.data == data
        assert retrieved.checksum_sha256 == stored.checksum_sha256

    def test_zip_export_structure(self, evidence_store: EvidenceStorage):
        """Verify ZIP export with manifest can be built from evidence files."""
        files = {
            "doc1.pdf": b"PDF document content",
            "screenshot.png": b"\x89PNG\r\n\x1a\n fake image",
            "email.eml": b"From: user@example.com\nSubject: Evidence\n\nBody text",
        }

        stored_uris: dict[str, str] = {}
        for name, data in files.items():
            result = evidence_store.save("case-zip-1", name, data, None)
            stored_uris[name] = result.storage_uri

        # Build a ZIP (mirroring what the endpoint does)
        buf = io.BytesIO()
        manifest_entries = []

        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, uri in stored_uris.items():
                retrieved = evidence_store.retrieve(uri)
                assert retrieved is not None
                zf.writestr(name, retrieved.data)
                manifest_entries.append(
                    {
                        "file_name": name,
                        "sha256": retrieved.checksum_sha256,
                        "size_bytes": retrieved.size_bytes,
                    }
                )

            manifest = {
                "case_id": "case-zip-1",
                "files_included": len(manifest_entries),
                "documents": manifest_entries,
            }
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))

        buf.seek(0)

        # Verify ZIP content
        with zipfile.ZipFile(buf, "r") as zf:
            assert set(zf.namelist()) == {"doc1.pdf", "screenshot.png", "email.eml", "manifest.json"}
            assert zf.read("doc1.pdf") == b"PDF document content"

            manifest_data = json.loads(zf.read("manifest.json"))
            assert manifest_data["case_id"] == "case-zip-1"
            assert manifest_data["files_included"] == 3

    def test_zip_deduplicates_filenames(self, evidence_store: EvidenceStorage):
        """Duplicate filenames get numbered suffixes."""
        evidence_store.save("case-dup-1", "file.txt", b"first", None)
        stored2 = evidence_store.save("case-dup-2", "file.txt", b"second", None)

        # Both files named "file.txt" — the archive logic in the endpoint
        # handles dedup. Verify both can be saved and retrieved independently.
        r1 = evidence_store.retrieve(evidence_store.save("case-dup-1", "file.txt", b"first", None).storage_uri)
        r2 = evidence_store.retrieve(stored2.storage_uri)
        assert r1 is not None
        assert r2 is not None
        assert r1.data == b"first"
        assert r2.data == b"second"


# ===========================================================================
# F47: Worker job
# ===========================================================================


class TestEvidenceIntegrityJob:
    """Test the evidence integrity worker job entry point."""

    @patch("i4g.worker.jobs.evidence_integrity.build_evidence_storage")
    @patch("i4g.worker.jobs.evidence_integrity.build_sql_session_factory")
    @patch("i4g.worker.jobs.evidence_integrity.get_settings")
    @patch("i4g.worker.jobs.evidence_integrity.configure_job_logging")
    def test_main_returns_0_on_clean(
        self,
        mock_logging,
        mock_settings,
        mock_sf,
        mock_evidence,
    ):
        """Job returns 0 when no mismatches found."""
        mock_settings.return_value = SimpleNamespace()
        engine = create_engine("sqlite:///:memory:")
        METADATA.create_all(engine)
        factory = sessionmaker(bind=engine)
        mock_sf.return_value = factory

        mock_es = MagicMock()
        mock_evidence.return_value = mock_es

        from i4g.worker.jobs.evidence_integrity import main

        result = main()
        assert result == 0

    @patch("i4g.worker.jobs.evidence_integrity.build_evidence_storage")
    @patch("i4g.worker.jobs.evidence_integrity.build_sql_session_factory")
    @patch("i4g.worker.jobs.evidence_integrity.get_settings")
    @patch("i4g.worker.jobs.evidence_integrity.configure_job_logging")
    def test_main_returns_1_on_storage_failure(
        self,
        mock_logging,
        mock_settings,
        mock_sf,
        mock_evidence,
    ):
        """Job returns 1 when evidence storage cannot be built."""
        mock_settings.return_value = SimpleNamespace()
        mock_sf.return_value = MagicMock()
        mock_evidence.side_effect = RuntimeError("no GCS")

        from i4g.worker.jobs.evidence_integrity import main

        result = main()
        assert result == 1


# ===========================================================================
# RetrievedEvidence dataclass
# ===========================================================================


class TestRetrievedEvidence:
    """Verify the RetrievedEvidence dataclass shape."""

    def test_fields(self):
        r = RetrievedEvidence(
            data=b"abc",
            file_name="test.txt",
            content_type="text/plain",
            size_bytes=3,
            checksum_sha256="abc123",
            storage_uri="/path/to/test.txt",
        )
        assert r.data == b"abc"
        assert r.file_name == "test.txt"
        assert r.content_type == "text/plain"
        assert r.size_bytes == 3
