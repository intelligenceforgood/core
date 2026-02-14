"""Data retention and GDPR compliance service.

Implements the two-phase purge strategy:
1. **Soft-delete:** Mark resolved cases older than ``retention_days`` with
   ``is_deleted=True`` and ``deleted_at=now()``.
2. **Hard purge:** Permanently remove soft-deleted cases older than
   ``retention_grace_days``, cascading to PII vault, evidence storage,
   vector store, and related tables without FK cascades.

Also provides GDPR export and GDPR delete operations.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from i4g.store.sql import (
    cases,
    review_actions,
    review_queue,
    scam_records,
    source_documents,
    intake_records,
    intake_attachments,
    intake_jobs,
)

LOGGER = logging.getLogger(__name__)

# Terminal statuses indicating a case has been resolved.
RESOLVED_STATUSES = frozenset({"closed", "accepted", "rejected"})


class RetentionService:
    """Orchestrates data retention, GDPR export, and GDPR deletion.

    Args:
        session_factory: SQLAlchemy session factory for the main database.
        vault_token_store: ``SqlAlchemyPiiTokenStore`` for PII vault operations
            (optional — skipped when ``None``).
        evidence_storage: ``EvidenceStorage`` for evidence file cleanup
            (optional — skipped when ``None``).
        vector_store: ``VectorStore`` for embedding cleanup
            (optional — skipped when ``None``).
    """

    def __init__(
        self,
        session_factory,
        *,
        vault_token_store=None,
        evidence_storage=None,
        vector_store=None,
    ) -> None:
        self._session_factory = session_factory
        self._vault_token_store = vault_token_store
        self._evidence_storage = evidence_storage
        self._vector_store = vector_store

    # ------------------------------------------------------------------
    # Phase 1: soft-delete
    # ------------------------------------------------------------------

    def soft_delete_expired_cases(self, retention_days: int) -> list[str]:
        """Mark resolved cases older than *retention_days* as deleted.

        Cases are eligible when:
        - ``status`` is in :data:`RESOLVED_STATUSES`
        - ``resolved_at`` (or ``updated_at`` as fallback) is older than the
          retention window
        - ``is_deleted`` is ``False``

        Returns:
            List of ``case_id`` values that were soft-deleted.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        now = datetime.now(timezone.utc)

        with self._session_factory() as session:
            # Find eligible cases
            stmt = (
                sa.select(cases.c.case_id)
                .where(
                    cases.c.status.in_(RESOLVED_STATUSES),
                    cases.c.is_deleted == sa.false(),
                    sa.or_(
                        sa.and_(cases.c.resolved_at.isnot(None), cases.c.resolved_at < cutoff),
                        sa.and_(cases.c.resolved_at.is_(None), cases.c.updated_at < cutoff),
                    ),
                )
            )
            rows = session.execute(stmt).fetchall()
            case_ids = [row.case_id for row in rows]

            if not case_ids:
                return []

            # Soft-delete in batch
            session.execute(
                sa.update(cases)
                .where(cases.c.case_id.in_(case_ids))
                .values(is_deleted=True, deleted_at=now)
            )
            session.commit()

        LOGGER.info("Soft-deleted %d cases older than %d days", len(case_ids), retention_days)
        return case_ids

    # ------------------------------------------------------------------
    # Phase 2: hard purge
    # ------------------------------------------------------------------

    def hard_purge_deleted_cases(self, grace_days: int) -> list[str]:
        """Permanently remove soft-deleted cases older than *grace_days*.

        Cascades to:
        - ``source_documents``, ``entities``, ``indicators`` (FK CASCADE)
        - ``scam_records``, ``review_queue``/``review_actions`` (manual)
        - ``intake_records``/``intake_attachments``/``intake_jobs`` (manual)
        - PII vault tokens (via ``vault_token_store``)
        - Evidence files (via ``evidence_storage``)
        - Vector embeddings (via ``vector_store``)

        Returns:
            List of ``case_id`` values that were hard-purged.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=grace_days)

        with self._session_factory() as session:
            stmt = (
                sa.select(cases.c.case_id)
                .where(
                    cases.c.is_deleted == sa.true(),
                    cases.c.deleted_at.isnot(None),
                    cases.c.deleted_at < cutoff,
                )
            )
            rows = session.execute(stmt).fetchall()
            case_ids = [row.case_id for row in rows]

        if not case_ids:
            return []

        LOGGER.info("Hard-purging %d soft-deleted cases (grace period %d days)", len(case_ids), grace_days)

        for case_id in case_ids:
            self._purge_single_case(case_id)

        return case_ids

    def _purge_single_case(self, case_id: str) -> None:
        """Hard-delete a single case and all related data."""

        # 1. Collect evidence URIs before deleting rows
        evidence_uris = self._collect_evidence_uris(case_id)

        # 2. Delete from non-cascaded tables first
        self._delete_related_rows(case_id)

        # 3. Delete the case row (cascades to source_documents, entities, etc.)
        with self._session_factory() as session:
            now = datetime.now(timezone.utc)
            session.execute(
                sa.update(cases)
                .where(cases.c.case_id == case_id)
                .values(purged_at=now)
            )
            session.execute(
                sa.delete(cases).where(cases.c.case_id == case_id)
            )
            session.commit()

        # 4. Clean PII vault
        if self._vault_token_store is not None:
            try:
                count = self._vault_token_store.delete_tokens_for_case(case_id)
                LOGGER.debug("Purged %d PII tokens for case %s", count, case_id)
            except Exception:
                LOGGER.exception("Failed to purge PII tokens for case %s", case_id)

        # 5. Clean evidence files
        if self._evidence_storage is not None:
            for uri in evidence_uris:
                try:
                    self._evidence_storage.delete(uri)
                except Exception:
                    LOGGER.warning("Failed to delete evidence %s for case %s", uri, case_id)

        # 6. Clean vector embeddings
        if self._vector_store is not None:
            try:
                self._vector_store.delete_record(case_id)
            except Exception:
                LOGGER.warning("Failed to delete vector embedding for case %s", case_id)

        LOGGER.info("Hard-purged case %s", case_id)

    def _collect_evidence_uris(self, case_id: str) -> list[str]:
        """Gather source_url values from source_documents for cleanup."""
        with self._session_factory() as session:
            stmt = (
                sa.select(source_documents.c.source_url)
                .where(source_documents.c.case_id == case_id)
                .where(source_documents.c.source_url.isnot(None))
            )
            rows = session.execute(stmt).fetchall()
        return [row.source_url for row in rows if row.source_url]

    def _delete_related_rows(self, case_id: str) -> None:
        """Delete rows from tables that lack FK CASCADE to cases."""
        with self._session_factory() as session:
            # Review actions → review_queue (need review_ids first)
            review_ids_stmt = sa.select(review_queue.c.review_id).where(review_queue.c.case_id == case_id)
            review_rows = session.execute(review_ids_stmt).fetchall()
            review_ids = [r.review_id for r in review_rows]

            if review_ids:
                session.execute(
                    sa.delete(review_actions).where(review_actions.c.review_id.in_(review_ids))
                )
                session.execute(
                    sa.delete(review_queue).where(review_queue.c.review_id.in_(review_ids))
                )

            # Scam records
            session.execute(
                sa.delete(scam_records).where(scam_records.c.case_id == case_id)
            )

            # Intake chain: attachments/jobs → records
            intake_ids_stmt = sa.select(intake_records.c.intake_id).where(intake_records.c.case_id == case_id)
            intake_rows = session.execute(intake_ids_stmt).fetchall()
            intake_ids = [r.intake_id for r in intake_rows]

            if intake_ids:
                session.execute(
                    sa.delete(intake_attachments).where(intake_attachments.c.intake_id.in_(intake_ids))
                )
                session.execute(
                    sa.delete(intake_jobs).where(intake_jobs.c.intake_id.in_(intake_ids))
                )
                session.execute(
                    sa.delete(intake_records).where(intake_records.c.intake_id.in_(intake_ids))
                )

            session.commit()

    # ------------------------------------------------------------------
    # GDPR export
    # ------------------------------------------------------------------

    def export_case_data(self, case_id: str) -> dict[str, Any]:
        """Return complete case data as a JSON-serializable dict for GDPR export.

        Includes: case record, source documents, entities, indicators,
        review queue entries, review actions, scam records, intake records,
        and PII token metadata (without decrypted values).

        Raises:
            KeyError: If the case does not exist.
        """
        with self._session_factory() as session:
            case_row = session.execute(
                sa.select(cases).where(cases.c.case_id == case_id)
            ).fetchone()

            if not case_row:
                raise KeyError(f"Case {case_id} not found")

            export: dict[str, Any] = {
                "case": self._row_to_dict(case_row),
                "source_documents": self._fetch_table_rows(session, source_documents, case_id),
                "review_queue": [],
                "review_actions": [],
                "scam_records": self._fetch_table_rows(session, scam_records, case_id),
                "intake_records": [],
            }

            # Review queue + actions
            rq_rows = session.execute(
                sa.select(review_queue).where(review_queue.c.case_id == case_id)
            ).fetchall()
            export["review_queue"] = [self._row_to_dict(r) for r in rq_rows]

            review_ids = [r._mapping["review_id"] for r in rq_rows]
            if review_ids:
                ra_rows = session.execute(
                    sa.select(review_actions).where(review_actions.c.review_id.in_(review_ids))
                ).fetchall()
                export["review_actions"] = [self._row_to_dict(r) for r in ra_rows]

            # Intake records
            ir_rows = session.execute(
                sa.select(intake_records).where(intake_records.c.case_id == case_id)
            ).fetchall()
            export["intake_records"] = [self._row_to_dict(r) for r in ir_rows]

        # PII token metadata (no decrypted values)
        if self._vault_token_store is not None:
            try:
                tokens = self._vault_token_store.list_tokens()
                export["pii_tokens"] = [
                    {"token": t.token, "prefix": t.prefix, "detector": t.detector, "created_at": t.created_at}
                    for t in tokens
                    if t.case_id == case_id
                ]
            except Exception:
                LOGGER.warning("Could not export PII tokens for case %s", case_id)
                export["pii_tokens"] = []

        export["exported_at"] = datetime.now(timezone.utc).isoformat()
        return export

    # ------------------------------------------------------------------
    # GDPR delete
    # ------------------------------------------------------------------

    def gdpr_delete_case(self, case_id: str) -> dict[str, Any]:
        """Hard-delete a case and all associated data (GDPR right-to-erasure).

        Unlike retention purge, this is an immediate hard delete with no
        grace period. The delete is unconditional — any status is accepted.

        Returns:
            Summary of what was deleted.
        """
        # Verify case exists
        with self._session_factory() as session:
            row = session.execute(
                sa.select(cases.c.case_id).where(cases.c.case_id == case_id)
            ).fetchone()
            if not row:
                raise KeyError(f"Case {case_id} not found")

        evidence_uris = self._collect_evidence_uris(case_id)
        self._delete_related_rows(case_id)

        with self._session_factory() as session:
            session.execute(sa.delete(cases).where(cases.c.case_id == case_id))
            session.commit()

        pii_count = 0
        if self._vault_token_store is not None:
            try:
                pii_count = self._vault_token_store.delete_tokens_for_case(case_id)
            except Exception:
                LOGGER.exception("Failed to purge PII tokens during GDPR delete for case %s", case_id)

        evidence_deleted = 0
        if self._evidence_storage is not None:
            for uri in evidence_uris:
                try:
                    if self._evidence_storage.delete(uri):
                        evidence_deleted += 1
                except Exception:
                    LOGGER.warning("Failed to delete evidence %s", uri)

        vector_deleted = False
        if self._vector_store is not None:
            try:
                vector_deleted = self._vector_store.delete_record(case_id)
            except Exception:
                LOGGER.warning("Failed to delete vector record for case %s", case_id)

        return {
            "case_id": case_id,
            "deleted": True,
            "pii_tokens_removed": pii_count,
            "evidence_files_removed": evidence_deleted,
            "vector_embedding_removed": vector_deleted,
            "deleted_at": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_dict(row) -> dict[str, Any]:
        """Convert a SQLAlchemy Row to a JSON-safe dict."""
        data = dict(row._mapping)
        for k, v in data.items():
            if isinstance(v, datetime):
                data[k] = v.isoformat()
            elif isinstance(v, bytes):
                data[k] = "<binary>"
        return data

    def _fetch_table_rows(self, session: Session, table, case_id: str) -> list[dict[str, Any]]:
        """Fetch all rows for a case from a table with a case_id column."""
        rows = session.execute(
            sa.select(table).where(table.c.case_id == case_id)
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]
