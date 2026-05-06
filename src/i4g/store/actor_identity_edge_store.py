"""ActorIdentityEdgeStore: upsert and graph traversal for actor_identity_edges."""

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


class ActorIdentityEdgeStore:
    """SQLAlchemy-backed store for actor identity edge records."""

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

    def upsert_edge(
        self,
        *,
        source_identity_id: str,
        target_identity_id: str,
        edge_type: str,
        weight: float | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Insert or update an edge keyed on (source_identity_id, target_identity_id, edge_type).

        Uses SELECT → INSERT/UPDATE for SQLite/PostgreSQL portability.
        Returns the final row dict.
        """
        tbl = sql_schema.actor_identity_edges
        now = datetime.now(UTC)
        with self._session_factory() as session:
            existing = session.execute(
                sa.select(tbl).where(
                    sa.and_(
                        tbl.c.source_identity_id == source_identity_id,
                        tbl.c.target_identity_id == target_identity_id,
                        tbl.c.edge_type == edge_type,
                    )
                )
            ).first()
            if existing is None:
                edge_id = str(uuid.uuid4())
                row = {
                    "edge_id": edge_id,
                    "source_identity_id": source_identity_id,
                    "target_identity_id": target_identity_id,
                    "edge_type": edge_type,
                    "weight": weight,
                    "evidence": evidence,
                    "created_at": now,
                    "updated_at": now,
                }
                session.execute(sa.insert(tbl).values(row))
            else:
                edge_id = existing._mapping["edge_id"]
                update_vals: dict[str, Any] = {"updated_at": now}
                if weight is not None:
                    update_vals["weight"] = weight
                if evidence is not None:
                    update_vals["evidence"] = evidence
                session.execute(sa.update(tbl).where(tbl.c.edge_id == edge_id).values(**update_vals))
            session.commit()

        with self._session_factory() as session:
            result = session.execute(sa.select(tbl).where(tbl.c.edge_id == edge_id)).first()
            return dict(result._mapping)

    def neighbors(self, identity_id: str) -> list[dict[str, Any]]:
        """Return all edges where the identity is source or target."""
        tbl = sql_schema.actor_identity_edges
        stmt = sa.select(tbl).where(
            sa.or_(
                tbl.c.source_identity_id == identity_id,
                tbl.c.target_identity_id == identity_id,
            )
        )
        with self._session_factory() as session:
            rows = session.execute(stmt).fetchall()
            return [dict(r._mapping) for r in rows]

    def list_all_edges(self, *, limit: int = 1000, offset: int = 0) -> list[dict[str, Any]]:
        """Return all edges."""
        tbl = sql_schema.actor_identity_edges
        stmt = sa.select(tbl).order_by(tbl.c.created_at.asc()).limit(limit).offset(offset)
        with self._session_factory() as session:
            rows = session.execute(stmt).fetchall()
            return [dict(r._mapping) for r in rows]
