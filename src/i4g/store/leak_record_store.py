"""LeakRecordStore: CRUD for leak_records table."""

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


class LeakRecordStore:
    """SQLAlchemy-backed store for leak records."""

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

    def upsert(
        self,
        *,
        actor_id: str,
        breach_name: str,
        email: str | None = None,
        password_cleartext: str | None = None,
        password_hash: str | None = None,
        ip_address: str | None = None,
        leak_date: datetime | None = None,
        metadata_json: dict[str, Any] | None = None,
        source_provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Upsert a leak record by source_provenance key."""
        now = datetime.now(UTC)
        row = {
            "actor_id": actor_id,
            "breach_name": breach_name,
            "email": email,
            "password_cleartext": password_cleartext,
            "password_hash": password_hash,
            "ip_address": ip_address,
            "leak_date": leak_date,
            "metadata_json": metadata_json,
            "source_provenance": source_provenance,
            "updated_at": now,
        }

        tbl = sql_schema.leak_records

        with self._session_factory() as session:
            existing = None
            if source_provenance and "commit_sha" in source_provenance and "record_id" in source_provenance:
                stmt = sa.select(tbl).where((tbl.c.actor_id == actor_id) & (tbl.c.breach_name == breach_name))
                results = session.execute(stmt).fetchall()
                for r in results:
                    prov = r._mapping.get("source_provenance")
                    if (
                        prov
                        and source_provenance
                        and (
                            prov.get("commit_sha") == source_provenance.get("commit_sha")
                            and prov.get("team") == source_provenance.get("team")
                            and prov.get("record_id") == source_provenance.get("record_id")
                        )
                    ):
                        existing = dict(r._mapping)
                        break

            if existing:
                leak_id = existing["leak_id"]
                update_stmt = sa.update(tbl).where(tbl.c.leak_id == leak_id).values(**row)
                session.execute(update_stmt)
                session.commit()
                row["leak_id"] = leak_id
                row["created_at"] = existing["created_at"]
                return row
            else:
                leak_id = str(uuid.uuid4())
                row["leak_id"] = leak_id
                row["created_at"] = now
                session.execute(sa.insert(tbl).values(row))
                session.commit()
                return row

    def get(self, leak_id: str) -> dict[str, Any] | None:
        """Return a single leak record by ID."""
        tbl = sql_schema.leak_records
        with self._session_factory() as session:
            result = session.execute(sa.select(tbl).where(tbl.c.leak_id == leak_id)).first()
            if result is None:
                return None
            return dict(result._mapping)

    def list_by_actor(self, actor_id: str, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """List leak records for a specific actor."""
        tbl = sql_schema.leak_records
        stmt = (
            sa.select(tbl)
            .where(tbl.c.actor_id == actor_id)
            .order_by(tbl.c.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        with self._session_factory() as session:
            rows = session.execute(stmt).fetchall()
            return [dict(r._mapping) for r in rows]
