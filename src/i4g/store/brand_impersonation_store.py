"""BrandImpersonationStore: CRUD and upsert for brand_impersonations table."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from i4g.store import sql as sql_schema
from i4g.store.sql import METADATA
from i4g.store.sql import session_factory as default_session_factory


class BrandImpersonationStore:
    """SQLAlchemy-backed store for brand impersonation records."""

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

    def upsert_by_indicator_brand(
        self,
        *,
        indicator_id: str,
        brand: str,
        confidence: Decimal | None = None,
        detected_by: str | None = None,
        metadata_json: dict[str, Any] | None = None,
        source_provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Insert or update a brand impersonation keyed on (indicator_id, brand).

        The UNIQUE constraint on (indicator_id, brand) ensures exactly one row per pair.
        On update, all content fields are refreshed; created_at is preserved.
        Returns the final row dict.
        """
        tbl = sql_schema.brand_impersonations
        now = datetime.now(UTC)

        with self._session_factory() as session:
            existing = session.execute(
                sa.select(tbl).where(
                    sa.and_(
                        tbl.c.indicator_id == indicator_id,
                        tbl.c.brand == brand,
                    )
                )
            ).first()

            if existing is None:
                impersonation_id = str(uuid.uuid4())
                row = {
                    "impersonation_id": impersonation_id,
                    "indicator_id": indicator_id,
                    "brand": brand,
                    "confidence": confidence,
                    "detected_by": detected_by,
                    "metadata_json": metadata_json,
                    "source_provenance": source_provenance,
                    "created_at": now,
                    "updated_at": now,
                }
                session.execute(sa.insert(tbl).values(row))
            else:
                impersonation_id = existing._mapping["impersonation_id"]
                session.execute(
                    sa.update(tbl)
                    .where(tbl.c.impersonation_id == impersonation_id)
                    .values(
                        confidence=confidence,
                        detected_by=detected_by,
                        metadata_json=metadata_json,
                        source_provenance=source_provenance,
                        updated_at=now,
                    )
                )
            session.commit()

        with self._session_factory() as session:
            result = session.execute(sa.select(tbl).where(tbl.c.impersonation_id == impersonation_id)).first()
            return dict(result._mapping)

    def list_by_indicator(self, indicator_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        """Return brand impersonations for a given indicator, ordered by brand."""
        tbl = sql_schema.brand_impersonations
        stmt = sa.select(tbl).where(tbl.c.indicator_id == indicator_id).order_by(tbl.c.brand.asc()).limit(limit)
        with self._session_factory() as session:
            rows = session.execute(stmt).fetchall()
            return [dict(r._mapping) for r in rows]

    def list_by_brand(self, brand: str, *, limit: int = 100) -> list[dict[str, Any]]:
        """Return brand impersonations for a given brand across all indicators."""
        tbl = sql_schema.brand_impersonations
        stmt = sa.select(tbl).where(tbl.c.brand == brand).order_by(tbl.c.created_at.desc()).limit(limit)
        with self._session_factory() as session:
            rows = session.execute(stmt).fetchall()
            return [dict(r._mapping) for r in rows]
