"""ActorIdentityStore: upsert and lookup for actor_identities table."""

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


class ActorIdentityStore:
    """SQLAlchemy-backed store for actor identity records."""

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

    def upsert_by_handle(
        self,
        *,
        actor_id: str,
        platform: str,
        handle: str,
        platform_user_id: str | None = None,
        username_history: list[str] | None = None,
        display_name_history: list[str] | None = None,
        first_seen_at: datetime | None = None,
        last_seen_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
        source_provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Insert or update an actor identity keyed on (platform, handle).

        Uses a SELECT → INSERT/UPDATE pattern for SQLite/PostgreSQL portability.
        Returns the final row dict.
        """
        tbl = sql_schema.actor_identities
        now = datetime.now(UTC)
        with self._session_factory() as session:
            existing = session.execute(
                sa.select(tbl).where(sa.and_(tbl.c.platform == platform, tbl.c.handle == handle))
            ).first()
            if existing is None:
                identity_id = str(uuid.uuid4())
                row = {
                    "identity_id": identity_id,
                    "actor_id": actor_id,
                    "platform": platform,
                    "handle": handle,
                    "platform_user_id": platform_user_id,
                    "username_history": username_history,
                    "display_name_history": display_name_history,
                    "first_seen_at": first_seen_at,
                    "last_seen_at": last_seen_at,
                    "metadata": metadata,
                    "source_provenance": source_provenance,
                    "created_at": now,
                    "updated_at": now,
                }
                session.execute(sa.insert(tbl).values(row))
            else:
                identity_id = existing._mapping["identity_id"]
                update_vals: dict[str, Any] = {"updated_at": now}
                if platform_user_id is not None:
                    update_vals["platform_user_id"] = platform_user_id
                if username_history is not None:
                    update_vals["username_history"] = username_history
                if display_name_history is not None:
                    update_vals["display_name_history"] = display_name_history
                if last_seen_at is not None:
                    update_vals["last_seen_at"] = last_seen_at
                if metadata is not None:
                    update_vals["metadata"] = metadata
                if source_provenance is not None:
                    update_vals["source_provenance"] = source_provenance
                session.execute(sa.update(tbl).where(tbl.c.identity_id == identity_id).values(**update_vals))
            session.commit()

        with self._session_factory() as session:
            result = session.execute(sa.select(tbl).where(tbl.c.identity_id == identity_id)).first()
            return dict(result._mapping)

    def find_by_handle(self, platform: str, handle: str) -> dict[str, Any] | None:
        """Find an actor identity by platform and handle."""
        tbl = sql_schema.actor_identities
        with self._session_factory() as session:
            row = session.execute(
                sa.select(tbl).where(sa.and_(tbl.c.platform == platform, tbl.c.handle == handle))
            ).first()
            if row is None:
                return None
            return dict(row._mapping)

    def list_by_actor(self, actor_id: str, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """List all identities for a given actor."""
        tbl = sql_schema.actor_identities
        stmt = (
            sa.select(tbl)
            .where(tbl.c.actor_id == actor_id)
            .order_by(tbl.c.created_at.asc())
            .limit(limit)
            .offset(offset)
        )
        with self._session_factory() as session:
            rows = session.execute(stmt).fetchall()
            return [dict(r._mapping) for r in rows]

    def append_username_history(self, identity_id: str, username: str) -> dict[str, Any] | None:
        """Append a username to the username_history list for an identity.

        Returns the updated row, or None if not found.
        """
        tbl = sql_schema.actor_identities
        with self._session_factory() as session:
            row = session.execute(sa.select(tbl).where(tbl.c.identity_id == identity_id)).first()
            if row is None:
                return None
            current: list[str] = row._mapping["username_history"] or []
            if username not in current:
                current = [*current, username]
            session.execute(
                sa.update(tbl)
                .where(tbl.c.identity_id == identity_id)
                .values(username_history=current, updated_at=datetime.now(UTC))
            )
            session.commit()
            result = session.execute(sa.select(tbl).where(tbl.c.identity_id == identity_id)).first()
            return dict(result._mapping)
