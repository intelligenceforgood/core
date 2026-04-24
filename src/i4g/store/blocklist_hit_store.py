"""BlocklistHitStore: upsert and lookup for blocklist_hits table."""

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


class BlocklistHitStore:
    """SQLAlchemy-backed store for blocklist hit records."""

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
        indicator_id: str,
        source: str,
        first_seen_at: datetime | None = None,
        last_seen_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
        source_provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Insert or update a blocklist hit keyed on (indicator_id, source).

        Uses SELECT → INSERT/UPDATE for SQLite/PostgreSQL portability.
        Returns the final row dict.
        """
        tbl = sql_schema.blocklist_hits
        now = datetime.now(UTC)
        with self._session_factory() as session:
            existing = session.execute(
                sa.select(tbl).where(sa.and_(tbl.c.indicator_id == indicator_id, tbl.c.source == source))
            ).first()
            if existing is None:
                hit_id = str(uuid.uuid4())
                row = {
                    "hit_id": hit_id,
                    "indicator_id": indicator_id,
                    "source": source,
                    "first_seen_at": first_seen_at,
                    "last_seen_at": last_seen_at,
                    "metadata": metadata,
                    "source_provenance": source_provenance,
                    "created_at": now,
                    "updated_at": now,
                }
                session.execute(sa.insert(tbl).values(row))
            else:
                hit_id = existing._mapping["hit_id"]
                update_vals: dict[str, Any] = {"updated_at": now}
                if last_seen_at is not None:
                    update_vals["last_seen_at"] = last_seen_at
                if metadata is not None:
                    update_vals["metadata"] = metadata
                if source_provenance is not None:
                    update_vals["source_provenance"] = source_provenance
                session.execute(sa.update(tbl).where(tbl.c.hit_id == hit_id).values(**update_vals))
            session.commit()

        with self._session_factory() as session:
            result = session.execute(sa.select(tbl).where(tbl.c.hit_id == hit_id)).first()
            return dict(result._mapping)

    def list_by_indicator(self, indicator_id: str, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """List all blocklist hits for a given indicator."""
        tbl = sql_schema.blocklist_hits
        stmt = (
            sa.select(tbl)
            .where(tbl.c.indicator_id == indicator_id)
            .order_by(tbl.c.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        with self._session_factory() as session:
            rows = session.execute(stmt).fetchall()
            return [dict(r._mapping) for r in rows]

    def list_by_source(self, source: str, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """List all blocklist hits from a given source."""
        tbl = sql_schema.blocklist_hits
        stmt = (
            sa.select(tbl).where(tbl.c.source == source).order_by(tbl.c.created_at.desc()).limit(limit).offset(offset)
        )
        with self._session_factory() as session:
            rows = session.execute(stmt).fetchall()
            return [dict(r._mapping) for r in rows]
