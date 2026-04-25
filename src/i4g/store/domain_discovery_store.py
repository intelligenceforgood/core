"""DomainDiscoveryStore: insert and lookup for domain_discoveries staging table."""

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


class DomainDiscoveryStore:
    """SQLAlchemy-backed store for domain discovery staging records."""

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

    def insert(
        self,
        *,
        domain: str,
        source: str,
        seen_at: datetime,
        subject_common_name: str | None = None,
        not_before: datetime | None = None,
        filter_match: bool = False,
        filter_reason: str | None = None,
        enqueued_scan_id: str | None = None,
        raw: dict[str, Any] | None = None,
        source_provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Insert a new domain discovery record and return its dict."""
        discovery_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        row = {
            "discovery_id": discovery_id,
            "domain": domain,
            "subject_common_name": subject_common_name,
            "not_before": not_before,
            "source": source,
            "seen_at": seen_at,
            "filter_match": filter_match,
            "filter_reason": filter_reason,
            "enqueued_scan_id": enqueued_scan_id,
            "raw": raw,
            "source_provenance": source_provenance,
            "created_at": now,
            "updated_at": now,
        }
        with self._session_factory() as session:
            session.execute(sa.insert(sql_schema.domain_discoveries).values(row))
            session.commit()
        return row

    def list_recent_matches(
        self, *, limit: int = 100, offset: int = 0, since: datetime | None = None
    ) -> list[dict[str, Any]]:
        """Return domain discoveries where filter_match is True and not dismissed, newest first."""
        tbl = sql_schema.domain_discoveries
        predicate = sa.and_(tbl.c.filter_match == sa.true(), tbl.c.dismissed_at.is_(None))
        if since is not None:
            predicate = sa.and_(predicate, tbl.c.seen_at >= since)
        stmt = sa.select(tbl).where(predicate).order_by(tbl.c.seen_at.desc()).limit(limit).offset(offset)
        with self._session_factory() as session:
            rows = session.execute(stmt).fetchall()
            return [dict(r._mapping) for r in rows]

    def count_recent_matches(self, *, since: datetime | None = None) -> int:
        """Return total count of filter-matched, non-dismissed discoveries."""
        tbl = sql_schema.domain_discoveries
        predicate = sa.and_(tbl.c.filter_match == sa.true(), tbl.c.dismissed_at.is_(None))
        if since is not None:
            predicate = sa.and_(predicate, tbl.c.seen_at >= since)
        stmt = sa.select(sa.func.count()).select_from(tbl).where(predicate)
        with self._session_factory() as session:
            return session.execute(stmt).scalar() or 0

    def mark_enqueued(self, discovery_id: str, scan_id: str) -> dict[str, Any] | None:
        """Set enqueued_scan_id on a discovery record. Returns updated row or None."""
        tbl = sql_schema.domain_discoveries
        now = datetime.now(UTC)
        with self._session_factory() as session:
            result = session.execute(sa.select(tbl).where(tbl.c.discovery_id == discovery_id)).first()
            if result is None:
                return None
            session.execute(
                sa.update(tbl)
                .where(tbl.c.discovery_id == discovery_id)
                .values(enqueued_scan_id=scan_id, updated_at=now)
            )
            session.commit()
            updated = session.execute(sa.select(tbl).where(tbl.c.discovery_id == discovery_id)).first()
            return dict(updated._mapping)

    def dismiss(self, discovery_id: str, reason: str | None) -> dict[str, Any] | None:
        """Soft-dismiss a discovery. Returns updated row dict or None if not found."""
        tbl = sql_schema.domain_discoveries
        now = datetime.now(UTC)
        with self._session_factory() as session:
            result = session.execute(sa.select(tbl).where(tbl.c.discovery_id == discovery_id)).first()
            if result is None:
                return None
            session.execute(
                sa.update(tbl)
                .where(tbl.c.discovery_id == discovery_id)
                .values(dismissed_at=now, dismiss_reason=reason, updated_at=now)
            )
            session.commit()
            updated = session.execute(sa.select(tbl).where(tbl.c.discovery_id == discovery_id)).first()
            return dict(updated._mapping)
