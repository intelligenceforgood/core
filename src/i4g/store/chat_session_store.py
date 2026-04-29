"""ChatSessionStore: CRUD and upsert for chat_sessions table."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from i4g.store import sql as sql_schema
from i4g.store.sql import METADATA
from i4g.store.sql import session_factory as default_session_factory


def _json_field_eq(session: sa.orm.Session, col: sa.Column, field: str, value: str) -> sa.ColumnElement:
    """Return a dialect-aware WHERE clause matching a top-level JSON field value."""
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        return col.op("->>")(field) == value
    return sa.func.json_extract(col, f"$.{field}") == value


class ChatSessionStore:
    """SQLAlchemy-backed store for chat session records."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        session_factory: sessionmaker | None = None,
    ) -> None:
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
            self._session_factory = default_session_factory()

        with self._session_factory() as session:
            if session.bind.dialect.name == "sqlite":
                METADATA.create_all(session.connection())

    def create(
        self,
        session_id: str | None = None,
        *,
        case_id: str | None = None,
        campaign_id: str | None = None,
        actor_id: str | None = None,
        chat_ref: str,
        message_count: int = 0,
        language: str | None = None,
        deposit_demand: bool = False,
        victim_confirmed_send: bool = False,
        started_at: datetime | None = None,
        last_message_at: datetime | None = None,
        evidence_blob_sha256: str | None = None,
        metadata_json: dict[str, Any] | None = None,
        source_provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Insert a new chat session and return its row dict."""
        sid = session_id or str(uuid.uuid4())
        now = datetime.now(UTC)
        row = {
            "session_id": sid,
            "case_id": case_id,
            "campaign_id": campaign_id,
            "actor_id": actor_id,
            "chat_ref": chat_ref,
            "message_count": message_count,
            "language": language,
            "deposit_demand": deposit_demand,
            "victim_confirmed_send": victim_confirmed_send,
            "started_at": started_at,
            "last_message_at": last_message_at,
            "evidence_blob_sha256": evidence_blob_sha256,
            "metadata_json": metadata_json,
            "source_provenance": source_provenance,
            "created_at": now,
            "updated_at": now,
        }
        tbl = sql_schema.chat_sessions
        with self._session_factory() as session:
            session.execute(sa.insert(tbl).values(row))
            session.commit()
        return row

    def get(self, session_id: str) -> dict[str, Any] | None:
        """Return a single chat session by ID, or None."""
        tbl = sql_schema.chat_sessions
        with self._session_factory() as session:
            result = session.execute(sa.select(tbl).where(tbl.c.session_id == session_id)).first()
            if result is None:
                return None
            return dict(result._mapping)

    def upsert_by_provenance(
        self,
        *,
        source_provenance: dict[str, Any],
        chat_ref: str,
        message_count: int = 0,
        case_id: str | None = None,
        campaign_id: str | None = None,
        actor_id: str | None = None,
        language: str | None = None,
        deposit_demand: bool = False,
        victim_confirmed_send: bool = False,
        started_at: datetime | None = None,
        last_message_at: datetime | None = None,
        evidence_blob_sha256: str | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Insert or update a chat session keyed on (source_provenance.source, source_provenance.record_id).

        Preserves created_at on update; refreshes updated_at and all content fields.
        Returns the final row dict.
        """
        tbl = sql_schema.chat_sessions
        prov_source = source_provenance["source"]
        prov_record_id = source_provenance["record_id"]
        now = datetime.now(UTC)

        with self._session_factory() as session:
            existing = session.execute(
                sa.select(tbl).where(
                    sa.and_(
                        _json_field_eq(session, tbl.c.source_provenance, "source", prov_source),
                        _json_field_eq(session, tbl.c.source_provenance, "record_id", prov_record_id),
                    )
                )
            ).first()

            if existing is None:
                sid = str(uuid.uuid4())
                row = {
                    "session_id": sid,
                    "case_id": case_id,
                    "campaign_id": campaign_id,
                    "actor_id": actor_id,
                    "chat_ref": chat_ref,
                    "message_count": message_count,
                    "language": language,
                    "deposit_demand": deposit_demand,
                    "victim_confirmed_send": victim_confirmed_send,
                    "started_at": started_at,
                    "last_message_at": last_message_at,
                    "evidence_blob_sha256": evidence_blob_sha256,
                    "metadata_json": metadata_json,
                    "source_provenance": source_provenance,
                    "created_at": now,
                    "updated_at": now,
                }
                session.execute(sa.insert(tbl).values(row))
                session.execute(
                    sa.insert(sql_schema.audit_log).values(
                        audit_id=str(uuid.uuid4()),
                        actor="system",
                        action="ingest_pii",
                        resource_type="chat_session",
                        resource_id=sid,
                        created_at=now,
                    )
                )
            else:
                sid = existing._mapping["session_id"]
                session.execute(
                    sa.update(tbl)
                    .where(tbl.c.session_id == sid)
                    .values(
                        case_id=case_id,
                        campaign_id=campaign_id,
                        actor_id=actor_id,
                        chat_ref=chat_ref,
                        message_count=message_count,
                        language=language,
                        deposit_demand=deposit_demand,
                        victim_confirmed_send=victim_confirmed_send,
                        started_at=started_at,
                        last_message_at=last_message_at,
                        evidence_blob_sha256=evidence_blob_sha256,
                        metadata_json=metadata_json,
                        source_provenance=source_provenance,
                        updated_at=now,
                    )
                )
                session.execute(
                    sa.insert(sql_schema.audit_log).values(
                        audit_id=str(uuid.uuid4()),
                        actor="system",
                        action="ingest_pii",
                        resource_type="chat_session",
                        resource_id=sid,
                        created_at=now,
                    )
                )
            session.commit()

        with self._session_factory() as session:
            result = session.execute(sa.select(tbl).where(tbl.c.session_id == sid)).first()
            return dict(result._mapping)

    def list_by_campaign(self, campaign_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        """Return chat sessions for a given campaign, newest first."""
        tbl = sql_schema.chat_sessions
        stmt = sa.select(tbl).where(tbl.c.campaign_id == campaign_id).order_by(tbl.c.created_at.desc()).limit(limit)
        with self._session_factory() as session:
            rows = session.execute(stmt).fetchall()
            return [dict(r._mapping) for r in rows]

    def list_by_actor(self, actor_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        """Return chat sessions for a given actor, newest first."""
        tbl = sql_schema.chat_sessions
        stmt = sa.select(tbl).where(tbl.c.actor_id == actor_id).order_by(tbl.c.created_at.desc()).limit(limit)
        with self._session_factory() as session:
            rows = session.execute(stmt).fetchall()
            return [dict(r._mapping) for r in rows]
