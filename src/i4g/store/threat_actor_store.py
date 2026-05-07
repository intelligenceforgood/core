"""ThreatActorStore: CRUD for threat_actors table."""

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


class ThreatActorStore:
    """SQLAlchemy-backed store for threat actor records."""

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
        *,
        display_name: str,
        role: str | None = None,
        campaign_id: str | None = None,
        real_name: str | None = None,
        confidence: float | None = None,
        first_seen_at: datetime | None = None,
        last_seen_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
        source_provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Insert a new threat actor and return its dict."""
        actor_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        row = {
            "actor_id": actor_id,
            "display_name": display_name,
            "role": role,
            "campaign_id": campaign_id,
            "real_name": real_name,
            "confidence": confidence,
            "first_seen_at": first_seen_at,
            "last_seen_at": last_seen_at,
            "metadata": metadata,
            "source_provenance": source_provenance,
            "created_at": now,
            "updated_at": now,
        }
        with self._session_factory() as session:
            session.execute(sa.insert(sql_schema.threat_actors).values(row))
            session.commit()
        return row

    def get(self, actor_id: str) -> dict[str, Any] | None:
        """Return a single threat actor by ID, or None."""
        tbl = sql_schema.threat_actors
        with self._session_factory() as session:
            result = session.execute(sa.select(tbl).where(tbl.c.actor_id == actor_id)).first()
            if result is None:
                return None
            return dict(result._mapping)

    def find_by_identity(self, identity_id: str) -> dict[str, Any] | None:
        """Return the threat actor linked to the given identity_id, or None."""
        tbl = sql_schema.threat_actors
        ai = sql_schema.actor_identities
        with self._session_factory() as session:
            result = session.execute(
                sa.select(tbl).join(ai, ai.c.actor_id == tbl.c.actor_id).where(ai.c.identity_id == identity_id)
            ).first()
            if result is None:
                return None
            return dict(result._mapping)

    def list_actors(
        self,
        *,
        role: str | None = None,
        campaign_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        min_confidence: float | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List threat actors with optional filtering."""
        tbl = sql_schema.threat_actors
        stmt = sa.select(tbl)

        if role:
            stmt = stmt.where(tbl.c.role == role)
        if campaign_id:
            stmt = stmt.where(tbl.c.campaign_id == campaign_id)
        if since:
            stmt = stmt.where(tbl.c.last_seen_at >= since)
        if until:
            stmt = stmt.where(tbl.c.last_seen_at <= until)
        if min_confidence is not None:
            stmt = stmt.where(tbl.c.confidence >= min_confidence)

        stmt = stmt.order_by(tbl.c.created_at.desc()).limit(limit).offset(offset)

        with self._session_factory() as session:
            rows = session.execute(stmt).fetchall()
            return [dict(r._mapping) for r in rows]

    def list_by_campaign(self, campaign_id: str, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """List threat actors associated with a campaign."""
        tbl = sql_schema.threat_actors
        stmt = (
            sa.select(tbl)
            .where(tbl.c.campaign_id == campaign_id)
            .order_by(tbl.c.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        with self._session_factory() as session:
            rows = session.execute(stmt).fetchall()
            return [dict(r._mapping) for r in rows]
