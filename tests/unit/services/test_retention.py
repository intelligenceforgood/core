"""Unit tests for the RetentionService and related components (WS-6).

Covers:
- Soft-delete expired cases (F37)
- Hard-purge with cascade (F37, F41)
- GDPR data export (F39)
- GDPR deletion (F40)
- Retention window configurability (F38)
- PII vault + evidence cleanup (F41)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from i4g.services.retention import RESOLVED_STATUSES, RetentionService
from i4g.store.sql import METADATA, cases, review_actions, review_queue, scam_records, source_documents


@pytest.fixture()
def db_session_factory(tmp_path: Path):
    """In-memory SQLite session factory with all tables created."""
    engine = create_engine("sqlite:///:memory:")
    METADATA.create_all(engine)
    factory = sessionmaker(bind=engine)
    return factory


@pytest.fixture()
def mock_vault():
    """Mock vault token store with delete_tokens_for_case."""
    store = MagicMock()
    store.delete_tokens_for_case.return_value = 3
    store.list_tokens.return_value = []
    return store


@pytest.fixture()
def mock_evidence():
    """Mock evidence storage with delete method."""
    storage = MagicMock()
    storage.delete.return_value = True
    return storage


@pytest.fixture()
def mock_vector():
    """Mock vector store with delete_record."""
    store = MagicMock()
    store.delete_record.return_value = True
    return store


@pytest.fixture()
def service(db_session_factory, mock_vault, mock_evidence, mock_vector):
    """RetentionService with all optional stores."""
    return RetentionService(
        db_session_factory,
        vault_token_store=mock_vault,
        evidence_storage=mock_evidence,
        vector_store=mock_vector,
    )


def _insert_case(
    session_factory,
    case_id: str,
    status: str = "open",
    is_deleted: bool = False,
    deleted_at: datetime | None = None,
    resolved_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> str:
    """Helper to insert a case row into the test database."""
    now = datetime.now(UTC)
    with session_factory() as session:
        session.execute(
            sa.insert(cases).values(
                case_id=case_id,
                dataset="test",
                source_type="test",
                raw_text_sha256=str(uuid.uuid4()),
                status=status,
                is_deleted=is_deleted,
                deleted_at=deleted_at,
                resolved_at=resolved_at,
                created_at=now,
                updated_at=updated_at or now,
            )
        )
        session.commit()
    return case_id


def _insert_source_document(session_factory, case_id: str, source_url: str | None = None) -> str:
    doc_id = str(uuid.uuid4())
    with session_factory() as session:
        session.execute(
            sa.insert(source_documents).values(
                document_id=doc_id,
                case_id=case_id,
                source_url=source_url,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        session.commit()
    return doc_id


def _insert_review(session_factory, case_id: str) -> str:
    review_id = str(uuid.uuid4())
    with session_factory() as session:
        session.execute(
            sa.insert(review_queue).values(
                review_id=review_id,
                case_id=case_id,
                queued_at=datetime.now(UTC),
                status="new",
            )
        )
        session.commit()
    return review_id


def _insert_review_action(session_factory, review_id: str) -> str:
    action_id = str(uuid.uuid4())
    with session_factory() as session:
        session.execute(
            sa.insert(review_actions).values(
                action_id=action_id,
                review_id=review_id,
                actor="test",
                action="test_action",
                created_at=datetime.now(UTC),
            )
        )
        session.commit()
    return action_id


def _insert_scam_record(session_factory, case_id: str) -> None:
    with session_factory() as session:
        session.execute(
            sa.insert(scam_records).values(
                case_id=case_id,
                text="test scam text",
                created_at=datetime.now(UTC),
            )
        )
        session.commit()


def _count_cases(session_factory) -> int:
    with session_factory() as session:
        return session.execute(sa.select(sa.func.count()).select_from(cases)).scalar()


# ---------------------------------------------------------------
# F38: Retention window configurability
# ---------------------------------------------------------------


class TestRetentionSettings:
    """Verify retention_days and retention_grace_days in settings."""

    def test_default_retention_days(self, monkeypatch):
        """Default retention_days is 90."""
        monkeypatch.delenv("I4G_STORAGE__RETENTION_DAYS", raising=False)
        monkeypatch.delenv("STORAGE__RETENTION_DAYS", raising=False)
        monkeypatch.delenv("STORAGE_RETENTION_DAYS", raising=False)
        from i4g.settings.sections.basic import StorageSettings

        s = StorageSettings()
        assert s.retention_days == 90

    def test_override_retention_days(self, monkeypatch):
        """retention_days is overridable via env var."""
        monkeypatch.setenv("STORAGE__RETENTION_DAYS", "30")
        from i4g.settings.sections.basic import StorageSettings

        s = StorageSettings()
        assert s.retention_days == 30

    def test_default_grace_days(self, monkeypatch):
        """Default retention_grace_days is 30."""
        monkeypatch.delenv("I4G_STORAGE__RETENTION_GRACE_DAYS", raising=False)
        monkeypatch.delenv("STORAGE__RETENTION_GRACE_DAYS", raising=False)
        monkeypatch.delenv("STORAGE_RETENTION_GRACE_DAYS", raising=False)
        from i4g.settings.sections.basic import StorageSettings

        s = StorageSettings()
        assert s.retention_grace_days == 30


# ---------------------------------------------------------------
# F37: Soft-delete expired cases
# ---------------------------------------------------------------


class TestSoftDelete:
    """Phase 1: Soft-delete resolved cases past retention window."""

    def test_soft_deletes_resolved_cases(self, service, db_session_factory):
        """Resolved cases older than retention window are soft-deleted."""
        old_date = datetime.now(UTC) - timedelta(days=100)
        _insert_case(db_session_factory, "case-old", status="closed", resolved_at=old_date)
        _insert_case(db_session_factory, "case-recent", status="closed", resolved_at=datetime.now(UTC))
        _insert_case(db_session_factory, "case-open", status="open", updated_at=old_date)

        result = service.soft_delete_expired_cases(retention_days=90)

        assert result == ["case-old"]

        # Verify is_deleted flag
        with db_session_factory() as session:
            row = session.execute(sa.select(cases).where(cases.c.case_id == "case-old")).fetchone()
            assert row._mapping["is_deleted"] is True
            assert row._mapping["deleted_at"] is not None

    def test_no_cases_to_soft_delete(self, service, db_session_factory):
        """Returns empty list when no cases qualify."""
        _insert_case(db_session_factory, "case-1", status="open")
        result = service.soft_delete_expired_cases(retention_days=90)
        assert result == []

    def test_respects_resolved_statuses(self, service, db_session_factory):
        """Only terminal statuses are eligible for soft-delete."""
        old_date = datetime.now(UTC) - timedelta(days=100)
        for s in RESOLVED_STATUSES:
            _insert_case(db_session_factory, f"case-{s}", status=s, resolved_at=old_date)
        _insert_case(db_session_factory, "case-in-review", status="in_review", updated_at=old_date)

        result = service.soft_delete_expired_cases(retention_days=90)
        assert len(result) == 3
        assert "case-in-review" not in result

    def test_uses_updated_at_fallback(self, service, db_session_factory):
        """Falls back to updated_at when resolved_at is NULL."""
        old_date = datetime.now(UTC) - timedelta(days=100)
        _insert_case(db_session_factory, "case-no-resolved", status="accepted", resolved_at=None, updated_at=old_date)

        result = service.soft_delete_expired_cases(retention_days=90)
        assert result == ["case-no-resolved"]

    def test_skips_already_deleted(self, service, db_session_factory):
        """Cases already marked is_deleted are not soft-deleted again."""
        old_date = datetime.now(UTC) - timedelta(days=100)
        _insert_case(
            db_session_factory,
            "already-deleted",
            status="closed",
            resolved_at=old_date,
            is_deleted=True,
            deleted_at=old_date,
        )
        result = service.soft_delete_expired_cases(retention_days=90)
        assert result == []


# ---------------------------------------------------------------
# F37 + F41: Hard-purge with cascade
# ---------------------------------------------------------------


class TestHardPurge:
    """Phase 2: Hard-purge soft-deleted cases after grace period."""

    def test_hard_purge_cascades(self, service, db_session_factory, mock_vault, mock_evidence, mock_vector):
        """Hard purge removes case + related data + PII + evidence + vectors."""
        old_deleted = datetime.now(UTC) - timedelta(days=40)
        case_id = _insert_case(
            db_session_factory, "case-purge", status="closed", is_deleted=True, deleted_at=old_deleted
        )
        _insert_source_document(db_session_factory, case_id, source_url="gs://bucket/evidence/file.pdf")
        review_id = _insert_review(db_session_factory, case_id)
        _insert_review_action(db_session_factory, review_id)
        _insert_scam_record(db_session_factory, case_id)

        result = service.hard_purge_deleted_cases(grace_days=30)

        assert result == ["case-purge"]
        assert _count_cases(db_session_factory) == 0
        mock_vault.delete_tokens_for_case.assert_called_once_with("case-purge")
        mock_evidence.delete.assert_called_once_with("gs://bucket/evidence/file.pdf")
        mock_vector.delete_record.assert_called_once_with("case-purge")

    def test_skips_recently_deleted(self, service, db_session_factory):
        """Cases soft-deleted within the grace period are not hard-purged."""
        recent = datetime.now(UTC) - timedelta(days=5)
        _insert_case(db_session_factory, "case-recent-del", status="closed", is_deleted=True, deleted_at=recent)

        result = service.hard_purge_deleted_cases(grace_days=30)
        assert result == []
        assert _count_cases(db_session_factory) == 1

    def test_hard_purge_cleans_review_chain(self, service, db_session_factory):
        """Review queue + review actions are cleaned before case deletion."""
        old_deleted = datetime.now(UTC) - timedelta(days=40)
        case_id = _insert_case(
            db_session_factory, "case-reviews", status="closed", is_deleted=True, deleted_at=old_deleted
        )
        review_id = _insert_review(db_session_factory, case_id)
        _insert_review_action(db_session_factory, review_id)

        service.hard_purge_deleted_cases(grace_days=30)

        with db_session_factory() as session:
            rq_count = session.execute(sa.select(sa.func.count()).select_from(review_queue)).scalar()
            ra_count = session.execute(sa.select(sa.func.count()).select_from(review_actions)).scalar()
            assert rq_count == 0
            assert ra_count == 0


# ---------------------------------------------------------------
# F39: GDPR data export
# ---------------------------------------------------------------


class TestGDPRExport:
    """GDPR export returns complete case data as JSON."""

    def test_export_includes_all_tables(self, service, db_session_factory):
        """Export returns case, source docs, reviews, scam records."""
        case_id = _insert_case(db_session_factory, "case-export", status="open")
        _insert_source_document(db_session_factory, case_id, source_url="/path/to/file.pdf")
        review_id = _insert_review(db_session_factory, case_id)
        _insert_review_action(db_session_factory, review_id)
        _insert_scam_record(db_session_factory, case_id)

        export = service.export_case_data("case-export")

        assert export["case"]["case_id"] == "case-export"
        assert len(export["source_documents"]) == 1
        assert len(export["review_queue"]) == 1
        assert len(export["review_actions"]) == 1
        assert len(export["scam_records"]) == 1
        assert "exported_at" in export

    def test_export_not_found(self, service):
        """KeyError raised for nonexistent case."""
        with pytest.raises(KeyError, match="Case nonexistent not found"):
            service.export_case_data("nonexistent")


# ---------------------------------------------------------------
# F40: GDPR deletion
# ---------------------------------------------------------------


class TestGDPRDelete:
    """GDPR delete immediately hard-removes a case regardless of status."""

    def test_gdpr_delete_removes_case(self, service, db_session_factory, mock_vault, mock_evidence, mock_vector):
        """Full cascade deletion via GDPR delete."""
        case_id = _insert_case(db_session_factory, "case-gdpr-del", status="open")
        _insert_source_document(db_session_factory, case_id, source_url="gs://b/evidence.pdf")
        _insert_scam_record(db_session_factory, case_id)

        result = service.gdpr_delete_case("case-gdpr-del")

        assert result["deleted"] is True
        assert result["case_id"] == "case-gdpr-del"
        assert result["pii_tokens_removed"] == 3
        assert result["evidence_files_removed"] == 1
        assert _count_cases(db_session_factory) == 0

    def test_gdpr_delete_not_found(self, service):
        """KeyError for nonexistent case on GDPR delete."""
        with pytest.raises(KeyError, match="Case missing not found"):
            service.gdpr_delete_case("missing")

    def test_gdpr_delete_open_case(self, service, db_session_factory):
        """GDPR delete works on any status, not just resolved."""
        _insert_case(db_session_factory, "case-open-gdpr", status="open")
        result = service.gdpr_delete_case("case-open-gdpr")
        assert result["deleted"] is True
        assert _count_cases(db_session_factory) == 0


# ---------------------------------------------------------------
# Service with no optional stores
# ---------------------------------------------------------------


class TestMinimalService:
    """RetentionService works without vault/evidence/vector stores."""

    def test_purge_without_optional_stores(self, db_session_factory):
        """Hard purge succeeds when optional stores are None."""
        svc = RetentionService(db_session_factory)
        old_deleted = datetime.now(UTC) - timedelta(days=40)
        _insert_case(db_session_factory, "case-minimal", status="closed", is_deleted=True, deleted_at=old_deleted)

        result = svc.hard_purge_deleted_cases(grace_days=30)
        assert result == ["case-minimal"]
        assert _count_cases(db_session_factory) == 0

    def test_export_without_vault(self, db_session_factory):
        """Export works without PII vault store."""
        svc = RetentionService(db_session_factory)
        _insert_case(db_session_factory, "case-no-vault", status="open")
        export = svc.export_case_data("case-no-vault")
        assert export["case"]["case_id"] == "case-no-vault"
