"""SQLite-backed intake storage for i4g."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from i4g.settings import get_settings
from i4g.store import sql as sql_schema
from i4g.store.sql import session_factory as default_session_factory

SETTINGS = get_settings()


class IntakeStore:
    """Persist victim intake records, attachments, and job status metadata."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        resolved = Path(db_path) if db_path else Path(SETTINGS.storage.sqlite_path)
        if not resolved.is_absolute():
            resolved = (Path(SETTINGS.project_root) / resolved).resolve()
        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            fallback = Path(os.getenv("I4G_RUNTIME__FALLBACK_DIR", "/tmp/i4g/sqlite")) / "intake.db"
            fallback.parent.mkdir(parents=True, exist_ok=True)
            resolved = fallback
        self.db_path = resolved
        self._init_tables()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self) -> None:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS intake_records (
                    intake_id TEXT PRIMARY KEY,
                    reporter_name TEXT,
                    contact_email TEXT,
                    contact_phone TEXT,
                    contact_handle TEXT,
                    preferred_contact TEXT,
                    incident_date TEXT,
                    loss_amount REAL,
                    summary TEXT,
                    details TEXT,
                    status TEXT,
                    submitted_by TEXT,
                    source TEXT,
                    case_id TEXT,
                    review_id TEXT,
                    job_id TEXT,
                    job_status TEXT,
                    job_message TEXT,
                    metadata TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS intake_attachments (
                    attachment_id TEXT PRIMARY KEY,
                    intake_id TEXT NOT NULL,
                    file_name TEXT,
                    content_type TEXT,
                    size_bytes INTEGER,
                    checksum_sha256 TEXT,
                    storage_uri TEXT,
                    storage_backend TEXT,
                    created_at TEXT,
                    FOREIGN KEY (intake_id) REFERENCES intake_records (intake_id)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS intake_jobs (
                    job_id TEXT PRIMARY KEY,
                    intake_id TEXT NOT NULL,
                    status TEXT,
                    message TEXT,
                    metadata TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    FOREIGN KEY (intake_id) REFERENCES intake_records (intake_id)
                )
                """
            )
            conn.commit()

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
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        intake_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO intake_records (
                    intake_id,
                    reporter_name,
                    contact_email,
                    contact_phone,
                    contact_handle,
                    preferred_contact,
                    incident_date,
                    loss_amount,
                    summary,
                    details,
                    status,
                    submitted_by,
                    source,
                    metadata,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    intake_id,
                    reporter_name,
                    contact_email,
                    contact_phone,
                    contact_handle,
                    preferred_contact,
                    incident_date,
                    loss_amount,
                    summary,
                    details,
                    "received",
                    submitted_by,
                    source,
                    json.dumps(metadata or {}),
                    now,
                    now,
                ),
            )
        return intake_id

    def update_intake_status(self, intake_id: str, status: str, message: Optional[str] = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE intake_records
                SET status = ?, job_message = COALESCE(?, job_message), updated_at = ?
                WHERE intake_id = ?
                """,
                (status, message, now, intake_id),
            )

    def attach_case(self, intake_id: str, *, case_id: Optional[str], review_id: Optional[str]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE intake_records
                SET case_id = COALESCE(?, case_id), review_id = COALESCE(?, review_id), updated_at = ?
                WHERE intake_id = ?
                """,
                (case_id, review_id, now, intake_id),
            )

    # ------------------------------------------------------------------
    # Attachments
    # ------------------------------------------------------------------
    def add_attachment(
        self,
        intake_id: str,
        *,
        file_name: str,
        content_type: Optional[str],
        size_bytes: int,
        checksum_sha256: str,
        storage_uri: str,
        storage_backend: str,
    ) -> str:
        attachment_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO intake_attachments (
                    attachment_id,
                    intake_id,
                    file_name,
                    content_type,
                    size_bytes,
                    checksum_sha256,
                    storage_uri,
                    storage_backend,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attachment_id,
                    intake_id,
                    file_name,
                    content_type,
                    size_bytes,
                    checksum_sha256,
                    storage_uri,
                    storage_backend,
                    created_at,
                ),
            )
        return attachment_id

    # ------------------------------------------------------------------
    # Jobs
    # ------------------------------------------------------------------
    def create_job(
        self,
        intake_id: str,
        *,
        status: str,
        message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO intake_jobs (
                    job_id,
                    intake_id,
                    status,
                    message,
                    metadata,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (job_id, intake_id, status, message, json.dumps(metadata or {}), now, now),
            )
            conn.execute(
                """
                UPDATE intake_records
                SET job_id = ?, job_status = ?, job_message = ?, updated_at = ?
                WHERE intake_id = ?
                """,
                (job_id, status, message, now, intake_id),
            )
        return job_id

    def update_job_status(
        self,
        job_id: str,
        *,
        status: str,
        message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            result = conn.execute(
                """
                UPDATE intake_jobs
                SET status = ?, message = ?, metadata = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (status, message, json.dumps(metadata or {}), now, job_id),
            )
            if result.rowcount == 0:
                return False
            conn.execute(
                """
                UPDATE intake_records
                SET job_status = ?, job_message = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (status, message, now, job_id),
            )
        return True

    # ------------------------------------------------------------------
    # Retrieval helpers
    # ------------------------------------------------------------------
    def get_intake(self, intake_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM intake_records WHERE intake_id = ?", (intake_id,)).fetchone()
            if not row:
                return None
            attachments = conn.execute(
                "SELECT * FROM intake_attachments WHERE intake_id = ? ORDER BY created_at ASC",
                (intake_id,),
            ).fetchall()
            job = None
            if row["job_id"]:
                job = conn.execute("SELECT * FROM intake_jobs WHERE job_id = ?", (row["job_id"],)).fetchone()
        record = dict(row)
        record["metadata"] = json.loads(record.get("metadata") or "{}")
        record["attachments"] = [dict(a) for a in attachments]
        if job:
            job_dict = dict(job)
            job_dict["metadata"] = json.loads(job_dict.get("metadata") or "{}")
            record["job"] = job_dict
        else:
            record["job"] = None
        return record

    def list_intakes(self, limit: int = 25) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM intake_records ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        results: List[Dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            data["metadata"] = json.loads(data.get("metadata") or "{}")
            results.append(data)
        return results

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM intake_jobs WHERE job_id = ?", (job_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        data["metadata"] = json.loads(data.get("metadata") or "{}")
        return data

class SqlAlchemyIntakeStore:
    """SQLAlchemy-backed intake storage for i4g."""

    def __init__(self, session_factory: sessionmaker | None = None) -> None:
        self._session_factory = session_factory or default_session_factory()
        # Create tables if they don't exist
        with self._session_factory() as session:
            sql_schema.METADATA.create_all(session.get_bind())

    def create_intake(
        self,
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
        metadata: Dict[str, Any] | None = None,
    ) -> str:
        intake_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        with self._session_factory() as session:
            session.execute(
                sa.insert(sql_schema.intake_records).values(
                    intake_id=intake_id,
                    reporter_name=reporter_name,
                    contact_email=contact_email,
                    contact_phone=contact_phone,
                    contact_handle=contact_handle,
                    preferred_contact=preferred_contact,
                    incident_date=incident_date,
                    loss_amount=loss_amount,
                    summary=summary,
                    details=details,
                    status="received",
                    submitted_by=submitted_by,
                    source=source,
                    metadata=metadata or {},
                    created_at=now,
                    updated_at=now,
                )
            )
            session.commit()
        return intake_id

    def add_attachment(
        self,
        intake_id: str,
        file_name: str,
        content_type: str | None,
        size_bytes: int,
        checksum_sha256: str,
        storage_uri: str,
        storage_backend: str,
    ) -> str:
        attachment_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
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

    def create_job(
        self,
        intake_id: str,
        status: str = "queued",
        message: str | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> str:
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
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
            # Also update intake record with job_id
            session.execute(
                sa.update(sql_schema.intake_records)
                .where(sql_schema.intake_records.c.intake_id == intake_id)
                .values(job_id=job_id, job_status=status, job_message=message, updated_at=now)
            )
            session.commit()
        return job_id

    def update_job(
        self,
        job_id: str,
        status: str,
        message: str | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> bool:
        now = datetime.now(timezone.utc)
        with self._session_factory() as session:
            # Get intake_id for this job
            job_row = session.execute(
                sa.select(sql_schema.intake_jobs.c.intake_id).where(sql_schema.intake_jobs.c.job_id == job_id)
            ).first()
            if not job_row:
                return False
            intake_id = job_row.intake_id

            values = {"status": status, "updated_at": now}
            if message is not None:
                values["message"] = message
            if metadata is not None:
                # Merge metadata? Or replace? SQLite implementation replaces.
                # But here we should probably merge if possible, but let's stick to replace for consistency.
                # Wait, SQLite implementation does:
                # current = json.loads(row["metadata"] or "{}")
                # current.update(metadata)
                # So it merges.
                
                # Fetch current metadata
                current_meta_row = session.execute(
                    sa.select(sql_schema.intake_jobs.c.metadata).where(sql_schema.intake_jobs.c.job_id == job_id)
                ).scalar()
                current_meta = dict(current_meta_row) if current_meta_row else {}
                current_meta.update(metadata)
                values["metadata"] = current_meta

            session.execute(
                sa.update(sql_schema.intake_jobs).where(sql_schema.intake_jobs.c.job_id == job_id).values(**values)
            )

            # Update intake record
            intake_values = {"job_status": status, "updated_at": now}
            if message is not None:
                intake_values["job_message"] = message
            
            session.execute(
                sa.update(sql_schema.intake_records)
                .where(sql_schema.intake_records.c.intake_id == intake_id)
                .values(**intake_values)
            )
            session.commit()
        return True

    def get_intake(self, intake_id: str) -> Optional[Dict[str, Any]]:
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

            record = dict(row._mapping)
            # Metadata is already a dict in SQLAlchemy if using JSON type
            record["metadata"] = record.get("metadata") or {}
            record["attachments"] = [dict(a._mapping) for a in attachments]
            
            if job:
                job_dict = dict(job._mapping)
                job_dict["metadata"] = job_dict.get("metadata") or {}
                record["job"] = job_dict
            else:
                record["job"] = None
            
            return record

    def list_intakes(self, limit: int = 25) -> List[Dict[str, Any]]:
        with self._session_factory() as session:
            rows = session.execute(
                sa.select(sql_schema.intake_records)
                .order_by(sql_schema.intake_records.c.created_at.desc())
                .limit(limit)
            ).all()
            
            results = []
            for row in rows:
                data = dict(row._mapping)
                data["metadata"] = data.get("metadata") or {}
                results.append(data)
            return results

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._session_factory() as session:
            row = session.execute(
                sa.select(sql_schema.intake_jobs).where(sql_schema.intake_jobs.c.job_id == job_id)
            ).first()
            if not row:
                return None
            data = dict(row._mapping)
            data["metadata"] = data.get("metadata") or {}
            return data
