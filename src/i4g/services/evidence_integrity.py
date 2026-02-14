"""Evidence integrity verification service (WS-7: F47).

Compares the SHA-256 hash stored in ``source_documents.file_sha256`` against the
actual hash of the file in storage. Reports mismatches and missing files.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa

from i4g.store.sql import source_documents

LOGGER = logging.getLogger(__name__)


@dataclass
class IntegrityResult:
    """Summary of a single evidence file check."""

    document_id: str
    case_id: str
    source_url: str
    expected_sha256: str | None
    actual_sha256: str | None
    status: str  # "ok", "mismatch", "missing", "no_hash", "error"
    detail: str | None = None


@dataclass
class IntegrityReport:
    """Aggregate result of a full integrity scan."""

    checked: int = 0
    ok: int = 0
    mismatches: int = 0
    missing: int = 0
    no_hash: int = 0
    errors: int = 0
    results: list[IntegrityResult] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""

    def summary(self) -> dict[str, Any]:
        """Return a JSON-safe summary dict (without per-file detail)."""
        return {
            "checked": self.checked,
            "ok": self.ok,
            "mismatches": self.mismatches,
            "missing": self.missing,
            "no_hash": self.no_hash,
            "errors": self.errors,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class EvidenceIntegrityService:
    """Verify stored evidence files against chain-of-custody hashes.

    Args:
        session_factory: SQLAlchemy session factory for the main database.
        evidence_storage: :class:`EvidenceStorage` instance used to retrieve
            files for hash comparison.
    """

    def __init__(self, session_factory, evidence_storage) -> None:
        self._session_factory = session_factory
        self._evidence_storage = evidence_storage

    def check_all(self, *, limit: int | None = None) -> IntegrityReport:
        """Verify integrity of all evidence files that have a ``source_url``.

        Args:
            limit: Maximum number of documents to check (``None`` for all).

        Returns:
            :class:`IntegrityReport` with per-file results.
        """
        report = IntegrityReport(started_at=datetime.now(timezone.utc).isoformat())

        with self._session_factory() as session:
            stmt = (
                sa.select(
                    source_documents.c.document_id,
                    source_documents.c.case_id,
                    source_documents.c.source_url,
                    source_documents.c.file_sha256,
                )
                .where(source_documents.c.source_url.isnot(None))
            )
            if limit is not None:
                stmt = stmt.limit(limit)
            rows = session.execute(stmt).fetchall()

        for row in rows:
            result = self._check_single(row)
            report.results.append(result)
            report.checked += 1
            if result.status == "ok":
                report.ok += 1
            elif result.status == "mismatch":
                report.mismatches += 1
            elif result.status == "missing":
                report.missing += 1
            elif result.status == "no_hash":
                report.no_hash += 1
            else:
                report.errors += 1

        report.finished_at = datetime.now(timezone.utc).isoformat()

        if report.mismatches > 0:
            LOGGER.warning(
                "Integrity check found %d mismatches out of %d files",
                report.mismatches,
                report.checked,
            )
        else:
            LOGGER.info(
                "Integrity check passed: %d files verified, %d missing, %d without hash",
                report.ok,
                report.missing,
                report.no_hash,
            )

        return report

    def _check_single(self, row) -> IntegrityResult:
        """Verify a single evidence file."""
        mapping = row._mapping
        doc_id = str(mapping["document_id"])
        case_id = str(mapping["case_id"])
        source_url = mapping["source_url"]
        expected_sha = mapping.get("file_sha256")

        if not expected_sha:
            return IntegrityResult(
                document_id=doc_id,
                case_id=case_id,
                source_url=source_url,
                expected_sha256=None,
                actual_sha256=None,
                status="no_hash",
                detail="No file_sha256 stored for comparison",
            )

        try:
            retrieved = self._evidence_storage.retrieve(source_url)
        except Exception as exc:
            return IntegrityResult(
                document_id=doc_id,
                case_id=case_id,
                source_url=source_url,
                expected_sha256=expected_sha,
                actual_sha256=None,
                status="error",
                detail=str(exc),
            )

        if retrieved is None:
            return IntegrityResult(
                document_id=doc_id,
                case_id=case_id,
                source_url=source_url,
                expected_sha256=expected_sha,
                actual_sha256=None,
                status="missing",
                detail="File not found at storage location",
            )

        actual_sha = retrieved.checksum_sha256
        if actual_sha != expected_sha:
            return IntegrityResult(
                document_id=doc_id,
                case_id=case_id,
                source_url=source_url,
                expected_sha256=expected_sha,
                actual_sha256=actual_sha,
                status="mismatch",
                detail=f"Expected {expected_sha}, got {actual_sha}",
            )

        return IntegrityResult(
            document_id=doc_id,
            case_id=case_id,
            source_url=source_url,
            expected_sha256=expected_sha,
            actual_sha256=actual_sha,
            status="ok",
        )

    def backfill_hashes(self) -> int:
        """Compute and store ``file_sha256`` for documents that have a
        ``source_url`` but no ``file_sha256`` yet.

        Returns:
            Number of documents updated.
        """
        with self._session_factory() as session:
            stmt = (
                sa.select(
                    source_documents.c.document_id,
                    source_documents.c.source_url,
                )
                .where(
                    source_documents.c.source_url.isnot(None),
                    sa.or_(
                        source_documents.c.file_sha256.is_(None),
                        source_documents.c.file_sha256 == "",
                    ),
                )
            )
            rows = session.execute(stmt).fetchall()

        updated = 0
        for row in rows:
            mapping = row._mapping
            doc_id = str(mapping["document_id"])
            source_url = mapping["source_url"]

            try:
                retrieved = self._evidence_storage.retrieve(source_url)
            except Exception:
                LOGGER.debug("Cannot retrieve %s for hash backfill", source_url)
                continue

            if retrieved is None:
                continue

            with self._session_factory() as session:
                session.execute(
                    sa.update(source_documents)
                    .where(source_documents.c.document_id == doc_id)
                    .values(file_sha256=retrieved.checksum_sha256)
                )
                session.commit()
            updated += 1

        LOGGER.info("Backfilled file_sha256 for %d documents", updated)
        return updated
