"""SQLAlchemy-backed structured storage layer for i4g.

This module provides a unified :class:`StructuredStore` that persists
:class:`ScamRecord` objects using SQLAlchemy Core.  It works transparently
with both SQLite (local development) and PostgreSQL (Cloud SQL) backends
by delegating dialect-specific details to the shared session factory in
:mod:`i4g.store.sql`.

The legacy raw-``sqlite3`` implementation was removed in the Store
Consolidation sprint (WS-3 / D16).  All callers now go through this
single SQLAlchemy path.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from i4g.store import sql as sql_schema
from i4g.store.schema import ScamRecord
from i4g.store.sql import (
    METADATA,
    dialect_insert,
)
from i4g.store.sql import session_factory as build_session_factory


def _ensure_dir_for_db(db_path: str | Path) -> None:
    """Ensure parent directory for the DB file exists."""
    p = Path(db_path)
    if p.parent:
        p.parent.mkdir(parents=True, exist_ok=True)


class StructuredStore:
    """SQLAlchemy-backed store for :class:`ScamRecord` objects.

    Accepts either a ``db_path`` (convenience for local SQLite) or a
    pre-configured ``session_factory``.  When neither is supplied the
    factory falls back to the project-wide settings via
    :func:`i4g.store.sql.session_factory`.
    """

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
            _ensure_dir_for_db(resolved)
            engine = sa.create_engine(
                f"sqlite:///{resolved}",
                connect_args={"check_same_thread": False, "timeout": 30},
                future=True,
            )
            self._session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
        else:
            # Defer to global settings
            self._session_factory = build_session_factory()

        # Auto-create tables only for SQLite (local dev convenience).
        # PostgreSQL schema is managed exclusively by Alembic migrations.
        with self._session_factory() as session:
            if session.bind.dialect.name == "sqlite":
                METADATA.create_all(session.connection())

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def close(self) -> None:
        """No-op kept for interface compatibility."""

    def _row_to_record(self, row: Any) -> ScamRecord:
        """Convert a SQLAlchemy Row to :class:`ScamRecord`."""
        created_at = row.created_at
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at)
            except (ValueError, TypeError):
                created_at = datetime.now(UTC)
        return ScamRecord(
            case_id=row.case_id,
            text=row.text,
            entities=row.entities or {},
            classification=row.classification,
            confidence=float(row.confidence) if row.confidence is not None else 0.0,
            created_at=created_at,
            embedding=row.embedding,
            metadata=row.metadata,
        )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def upsert_record(self, record: ScamRecord) -> None:
        """Insert or update a :class:`ScamRecord`."""
        with self._session_factory() as session:
            stmt = dialect_insert(session, sql_schema.scam_records).values(
                case_id=record.case_id,
                text=record.text,
                entities=record.entities,
                classification=record.classification,
                confidence=float(record.confidence),
                created_at=record.created_at,
                embedding=record.embedding,
                metadata=record.metadata,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["case_id"],
                set_={
                    "text": stmt.excluded.text,
                    "entities": stmt.excluded.entities,
                    "classification": stmt.excluded.classification,
                    "confidence": stmt.excluded.confidence,
                    "created_at": stmt.excluded.created_at,
                    "embedding": stmt.excluded.embedding,
                    "metadata": stmt.excluded.metadata,
                },
            )
            session.execute(stmt)
            session.commit()

    def get_by_id(self, case_id: str) -> ScamRecord | None:
        """Retrieve a record by ``case_id``."""
        with self._session_factory() as session:
            row = session.execute(
                sa.select(sql_schema.scam_records).where(sql_schema.scam_records.c.case_id == case_id)
            ).first()
            if not row:
                return None
            return self._row_to_record(row)

    def list_recent(self, limit: int = 50) -> list[ScamRecord]:
        """List the most recent records ordered by ``created_at`` descending."""
        with self._session_factory() as session:
            rows = session.execute(
                sa.select(sql_schema.scam_records).order_by(sql_schema.scam_records.c.created_at.desc()).limit(limit)
            ).all()
            return [self._row_to_record(r) for r in rows]

    def list_all(self) -> list[ScamRecord]:
        """Return every record in the store (used by batch jobs like PII backfill)."""
        with self._session_factory() as session:
            rows = session.execute(
                sa.select(sql_schema.scam_records).order_by(sql_schema.scam_records.c.created_at.asc())
            ).all()
            return [self._row_to_record(r) for r in rows]

    def search_by_field(self, field: str, value: Any, top_k: int = 50) -> list[ScamRecord]:
        """Search records by a top-level field or JSON entity key."""
        with self._session_factory() as session:
            query = sa.select(sql_schema.scam_records)
            dialect = session.get_bind().dialect.name

            # Confidence comparison operators
            if field == "confidence" and isinstance(value, str) and value.startswith((">", "<", ">=", "<=")):
                col = sql_schema.scam_records.c.confidence
                if value.startswith(">="):
                    query = query.where(col >= float(value[2:]))
                elif value.startswith("<="):
                    query = query.where(col <= float(value[2:]))
                elif value.startswith(">"):
                    query = query.where(col > float(value[1:]))
                elif value.startswith("<"):
                    query = query.where(col < float(value[1:]))
                query = query.order_by(col.desc())

            elif field in ("case_id", "classification"):
                query = query.where(getattr(sql_schema.scam_records.c, field) == value)

            elif field == "dataset":
                if dialect == "postgresql":
                    query = query.where(sql_schema.scam_records.c.metadata["dataset"].astext == str(value))
                else:
                    query = query.where(
                        sa.func.json_extract(sql_schema.scam_records.c.metadata, "$.dataset") == str(value)
                    )

            else:
                # Entity search — JOIN the entities table (authoritative source)
                e = sql_schema.entities
                query = query.join(e, e.c.case_id == sql_schema.scam_records.c.case_id).where(e.c.entity_type == field)
                if isinstance(value, str):
                    query = query.where(
                        sa.or_(
                            e.c.canonical_value.ilike(f"%{value}%"),
                            e.c.raw_value.ilike(f"%{value}%"),
                        )
                    )
                query = query.distinct()

            query = query.limit(top_k)
            rows = session.execute(query).all()
            return [self._row_to_record(r) for r in rows]

    def search_text(self, query: str, top_k: int = 50, offset: int = 0) -> list[ScamRecord]:
        """Run a case-insensitive substring search against case descriptions."""
        if not query:
            return []

        with self._session_factory() as session:
            pattern = f"%{query.strip()}%"
            c = sql_schema.cases
            sr = sql_schema.scam_records
            stmt = (
                sa.select(sr)
                .join(c, c.c.case_id == sr.c.case_id)
                .where(c.c.description.ilike(pattern))
                .order_by(sr.c.created_at.desc())
                .limit(top_k)
                .offset(offset)
            )
            rows = session.execute(stmt).all()
            return [self._row_to_record(r) for r in rows]

    def delete_by_id(self, case_id: str) -> bool:
        """Delete a record by ``case_id``. Returns ``True`` if a row was removed."""
        with self._session_factory() as session:
            result = session.execute(
                sa.delete(sql_schema.scam_records).where(sql_schema.scam_records.c.case_id == case_id)
            )
            session.commit()
            return result.rowcount > 0


# Backward-compatible alias so imports of ``SqlAlchemyStructuredStore`` keep
# working without changes.
SqlAlchemyStructuredStore = StructuredStore
