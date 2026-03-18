"""SQLAlchemy-backed intake storage for i4g.

Unified implementation that works with both SQLite and PostgreSQL.
The legacy raw-``sqlite3`` class was removed in the Store Consolidation
sprint (WS-3 / D16).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from i4g.pii.encryption import decrypt_value, encrypt_value
from i4g.store import sql as sql_schema
from i4g.store.sql import (
    METADATA,
)
from i4g.store.sql import session_factory as build_session_factory

logger = logging.getLogger(__name__)


class IntakeStore:
    """Persist victim intake records, attachments, and job status metadata.

    Accepts either a ``db_path`` (convenience for local SQLite) or a
    pre-configured ``session_factory``.

    When ``pii_key`` is provided, contact fields (``reporter_name``,
    ``contact_email``, ``contact_phone``, ``contact_handle``) are
    encrypted at rest with Fernet and decrypted transparently on read.
    """

    # Fields encrypted at rest when a PII key is configured.
    _ENCRYPTED_FIELDS = ("reporter_name", "contact_email", "contact_phone", "contact_handle")

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        session_factory: sessionmaker | None = None,
        pii_key: str | None = None,
    ) -> None:
        self._pii_key = pii_key
        if session_factory is not None:
            self._session_factory = session_factory
        elif db_path is not None:
            resolved = Path(db_path)
            resolved.parent.mkdir(parents=True, exist_ok=True)
            engine = sa.create_engine(
                f"sqlite:///{resolved}",
                connect_args={"check_same_thread": False, "timeout": 30},
                future=True,
            )
            self._session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
        else:
            self._session_factory = build_session_factory()

        # Ensure schema exists
        with self._session_factory() as session:
            conn = session.connection()
            METADATA.create_all(conn)

    def _encrypt(self, value: str | None) -> str | None:
        """Encrypt a contact field value if a PII key is configured."""
        if value is None or not self._pii_key:
            return value
        return encrypt_value(value, self._pii_key)

    def _decrypt(self, value: str | None) -> str | None:
        """Decrypt a contact field value if a PII key is configured."""
        if value is None or not self._pii_key:
            return value
        return decrypt_value(value, self._pii_key)

    def _encrypt_contact_fields(self, values: dict[str, Any]) -> dict[str, Any]:
        """Encrypt contact fields in a values dict before writing."""
        for field in self._ENCRYPTED_FIELDS:
            if field in values and values[field] is not None:
                values[field] = self._encrypt(values[field])
        return values

    def _decrypt_record(self, record: dict[str, Any]) -> dict[str, Any]:
        """Decrypt contact fields in a record dict after reading."""
        for field in self._ENCRYPTED_FIELDS:
            if field in record and record[field] is not None:
                record[field] = self._decrypt(record[field])
        return record

    # ------------------------------------------------------------------
    # Intake CRUD
    # ------------------------------------------------------------------

    def create_intake(
        self,
        *,
        reporter_name: str,
        summary: str,
        details: str,
        submitted_by: str,
        contact_email: str | None = None,
        contact_phone: str | None = None,
        contact_handle: str | None = None,
        preferred_contact: str | None = None,
        incident_date: str | None = None,
        loss_amount: float | None = None,
        source: str = "unknown",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        intake_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        with self._session_factory() as session:
            session.execute(
                sa.insert(sql_schema.intake_records).values(
                    **self._encrypt_contact_fields(
                        {
                            "intake_id": intake_id,
                            "reporter_name": reporter_name,
                            "contact_email": contact_email,
                            "contact_phone": contact_phone,
                            "contact_handle": contact_handle,
                            "preferred_contact": preferred_contact,
                            "incident_date": incident_date,
                            "loss_amount": loss_amount,
                            "summary": summary,
                            "details": details,
                            "status": "received",
                            "submitted_by": submitted_by,
                            "source": source,
                            "metadata": metadata or {},
                            "created_at": now,
                            "updated_at": now,
                        }
                    )
                )
            )
            session.commit()
        return intake_id

    def update_intake_status(self, intake_id: str, status: str, message: str | None = None) -> None:
        now = datetime.now(UTC)
        with self._session_factory() as session:
            values: dict[str, Any] = {"status": status, "updated_at": now}
            if message is not None:
                values["job_message"] = message
            session.execute(
                sa.update(sql_schema.intake_records)
                .where(sql_schema.intake_records.c.intake_id == intake_id)
                .values(**values)
            )
            session.commit()

    def attach_case(self, intake_id: str, *, case_id: str | None = None, review_id: str | None = None) -> None:
        now = datetime.now(UTC)
        with self._session_factory() as session:
            values: dict[str, Any] = {"updated_at": now}
            if case_id is not None:
                values["case_id"] = case_id
            if review_id is not None:
                values["review_id"] = review_id
            session.execute(
                sa.update(sql_schema.intake_records)
                .where(sql_schema.intake_records.c.intake_id == intake_id)
                .values(**values)
            )
            session.commit()

    # ------------------------------------------------------------------
    # Attachments
    # ------------------------------------------------------------------

    def add_attachment(
        self,
        intake_id: str,
        *,
        file_name: str,
        content_type: str | None,
        size_bytes: int,
        checksum_sha256: str,
        storage_uri: str,
        storage_backend: str,
    ) -> str:
        attachment_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        with self._session_factory() as session:
            session.execute(
                sa.insert(sql_schema.intake_attachments).values(
                    attachment_id=attachment_id,
                    intake_id=intake_id,
                    file_name=file_name,
                    content_type=content_type,
                    size_bytes=size_bytes,
                    checksum_sha256=checksum_sha256,
                    storage_uri=storage_uri,
                    storage_backend=storage_backend,
                    created_at=now,
                )
            )
            session.commit()
        return attachment_id

    # ------------------------------------------------------------------
    # Jobs
    # ------------------------------------------------------------------

    def create_job(
        self,
        intake_id: str,
        *,
        status: str = "queued",
        message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        job_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        with self._session_factory() as session:
            session.execute(
                sa.insert(sql_schema.intake_jobs).values(
                    job_id=job_id,
                    intake_id=intake_id,
                    status=status,
                    message=message,
                    metadata=metadata or {},
                    created_at=now,
                    updated_at=now,
                )
            )
            session.execute(
                sa.update(sql_schema.intake_records)
                .where(sql_schema.intake_records.c.intake_id == intake_id)
                .values(job_id=job_id, job_status=status, job_message=message, updated_at=now)
            )
            session.commit()
        return job_id

    def update_job_status(
        self,
        job_id: str,
        *,
        status: str,
        message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        now = datetime.now(UTC)
        with self._session_factory() as session:
            # Get intake_id for this job
            job_row = session.execute(
                sa.select(sql_schema.intake_jobs.c.intake_id).where(sql_schema.intake_jobs.c.job_id == job_id)
            ).first()
            if not job_row:
                return False

            values: dict[str, Any] = {"status": status, "updated_at": now}
            if message is not None:
                values["message"] = message
            if metadata is not None:
                values["metadata"] = metadata

            session.execute(
                sa.update(sql_schema.intake_jobs).where(sql_schema.intake_jobs.c.job_id == job_id).values(**values)
            )
            # Update intake record
            intake_values: dict[str, Any] = {"job_status": status, "updated_at": now}
            if message is not None:
                intake_values["job_message"] = message
            session.execute(
                sa.update(sql_schema.intake_records)
                .where(sql_schema.intake_records.c.intake_id == job_row.intake_id)
                .values(**intake_values)
            )
            session.commit()
        return True

    # ------------------------------------------------------------------
    # Intake-Indicator Links (S1-14)
    # ------------------------------------------------------------------

    def link_indicator(
        self,
        intake_id: str,
        indicator_id: str,
        *,
        confidence: float = 0.0,
        linked_by: str = "system",
    ) -> None:
        """Create an intake-indicator link.

        Args:
            intake_id: The intake record ID.
            indicator_id: The indicator UUID.
            confidence: LLM extraction confidence (0.0–1.0).
            linked_by: Who/what created the link.
        """
        now = datetime.now(UTC)
        with self._session_factory() as session:
            session.execute(
                sql_schema.dialect_insert(session, sql_schema.intake_indicator_links)
                .values(
                    intake_id=intake_id,
                    indicator_id=indicator_id,
                    confidence=confidence,
                    linked_by=linked_by,
                    created_at=now,
                )
                .on_conflict_do_nothing(constraint="pk_intake_indicator_links")
            )
            session.commit()

    def get_indicator_links(self, intake_id: str) -> list[dict[str, Any]]:
        """List all indicator links for an intake record.

        Args:
            intake_id: The intake record ID.

        Returns:
            List of link dicts.
        """
        iil = sql_schema.intake_indicator_links
        with self._session_factory() as session:
            rows = session.execute(sa.select(iil).where(iil.c.intake_id == intake_id)).all()
            return [dict(r._mapping) for r in rows]

    def get_intakes_for_indicator(self, indicator_id: str) -> list[dict[str, Any]]:
        """List all intake records linked to an indicator.

        Args:
            indicator_id: The indicator UUID.

        Returns:
            List of link dicts.
        """
        iil = sql_schema.intake_indicator_links
        with self._session_factory() as session:
            rows = session.execute(sa.select(iil).where(iil.c.indicator_id == indicator_id)).all()
            return [dict(r._mapping) for r in rows]

    # ------------------------------------------------------------------
    # Retrieval helpers
    # ------------------------------------------------------------------

    def get_intake(self, intake_id: str) -> dict[str, Any] | None:
        with self._session_factory() as session:
            row = session.execute(
                sa.select(sql_schema.intake_records).where(sql_schema.intake_records.c.intake_id == intake_id)
            ).first()
            if not row:
                return None

            attachments = session.execute(
                sa.select(sql_schema.intake_attachments)
                .where(sql_schema.intake_attachments.c.intake_id == intake_id)
                .order_by(sql_schema.intake_attachments.c.created_at.asc())
            ).all()

            job = None
            if row.job_id:
                job = session.execute(
                    sa.select(sql_schema.intake_jobs).where(sql_schema.intake_jobs.c.job_id == row.job_id)
                ).first()

            record = self._decrypt_record(dict(row._mapping))
            record["metadata"] = record.get("metadata") or {}
            record["attachments"] = [dict(a._mapping) for a in attachments]

            if job:
                job_dict = dict(job._mapping)
                job_dict["metadata"] = job_dict.get("metadata") or {}
                record["job"] = job_dict
            else:
                record["job"] = None

            return record

    def get_contact(self, intake_id: str, *, actor: str) -> dict[str, Any] | None:
        """Return decrypted victim contact fields with audit logging.

        Args:
            intake_id: The intake record to retrieve contact info for.
            actor: Username or identity of the requesting user (for audit).

        Returns:
            Dict with contact fields, or ``None`` if the intake does not exist.
        """
        with self._session_factory() as session:
            row = session.execute(
                sa.select(
                    sql_schema.intake_records.c.intake_id,
                    sql_schema.intake_records.c.reporter_name,
                    sql_schema.intake_records.c.contact_email,
                    sql_schema.intake_records.c.contact_phone,
                    sql_schema.intake_records.c.contact_handle,
                    sql_schema.intake_records.c.preferred_contact,
                ).where(sql_schema.intake_records.c.intake_id == intake_id)
            ).first()
            if not row:
                return None

            record = self._decrypt_record(dict(row._mapping))

            # Audit log the access
            session.execute(
                sa.insert(sql_schema.audit_log).values(
                    audit_id=str(uuid.uuid4()),
                    actor=actor,
                    action="view_contact",
                    resource_type="intake",
                    resource_id=intake_id,
                    created_at=datetime.now(UTC),
                )
            )
            session.commit()

            logger.info("victim contact accessed: intake_id=%s actor=%s", intake_id, actor)
            return record

    def list_intakes(self, limit: int = 25) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            rows = session.execute(
                sa.select(sql_schema.intake_records)
                .order_by(sql_schema.intake_records.c.created_at.desc())
                .limit(limit)
            ).all()

            results: list[dict[str, Any]] = []
            for row in rows:
                data = self._decrypt_record(dict(row._mapping))
                data["metadata"] = data.get("metadata") or {}
                results.append(data)
            return results

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._session_factory() as session:
            row = session.execute(
                sa.select(sql_schema.intake_jobs).where(sql_schema.intake_jobs.c.job_id == job_id)
            ).first()
            if not row:
                return None
            data = dict(row._mapping)
            data["metadata"] = data.get("metadata") or {}
            return data


# Backward-compatible alias
SqlAlchemyIntakeStore = IntakeStore
