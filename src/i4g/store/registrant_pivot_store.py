"""RegistrantPivotStore: CRUD for registrant_pivots table."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from i4g.store import sql as sql_schema
from i4g.store.sql import METADATA, dialect_insert
from i4g.store.sql import session_factory as default_session_factory


class RegistrantPivotStore:
    """SQLAlchemy-backed store for registrant pivots."""

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
        pivot_type: str,
        pivot_value: str,
        actor_id: str | None = None,
        first_seen_at: datetime | None = None,
        last_seen_at: datetime | None = None,
        metadata_json: dict[str, Any] | None = None,
        source_provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Upsert a registrant pivot. Unique by (pivot_type, pivot_value)."""
        now = datetime.now(UTC)
        tbl = sql_schema.registrant_pivots

        row = {
            "pivot_id": str(uuid.uuid4()),
            "pivot_type": pivot_type,
            "pivot_value": pivot_value,
            "actor_id": actor_id,
            "first_seen_at": first_seen_at,
            "last_seen_at": last_seen_at,
            "metadata_json": metadata_json,
            "source_provenance": source_provenance,
            "created_at": now,
            "updated_at": now,
        }

        with self._session_factory() as session:
            stmt = dialect_insert(session, tbl).values(row)
            update_dict = {
                "actor_id": stmt.excluded.actor_id,
                "first_seen_at": sa.func.coalesce(tbl.c.first_seen_at, stmt.excluded.first_seen_at),
                "metadata_json": stmt.excluded.metadata_json,
                "source_provenance": stmt.excluded.source_provenance,
                "updated_at": now,
            }
            if session.bind.dialect.name == "sqlite":
                update_dict["last_seen_at"] = stmt.excluded.last_seen_at
                stmt = stmt.on_conflict_do_update(index_elements=["pivot_type", "pivot_value"], set_=update_dict)
            else:
                update_dict["last_seen_at"] = sa.func.greatest(tbl.c.last_seen_at, stmt.excluded.last_seen_at)
                stmt = stmt.on_conflict_do_update(constraint="uq_registrant_pivots_type_value", set_=update_dict)

            session.execute(stmt)
            session.commit()

            result = session.execute(
                sa.select(tbl).where((tbl.c.pivot_type == pivot_type) & (tbl.c.pivot_value == pivot_value))
            ).first()
            return dict(result._mapping)

    def get(self, pivot_id: str) -> dict[str, Any] | None:
        """Return a single registrant pivot by ID."""
        tbl = sql_schema.registrant_pivots
        with self._session_factory() as session:
            result = session.execute(sa.select(tbl).where(tbl.c.pivot_id == pivot_id)).first()
            if result is None:
                return None
            return dict(result._mapping)

    def list_by_actor(self, actor_id: str, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """List registrant pivots for a specific actor."""
        tbl = sql_schema.registrant_pivots
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
