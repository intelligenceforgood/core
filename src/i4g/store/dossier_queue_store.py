"""SQLAlchemy-backed queue for dossier bundle plans.

Unified implementation that works with both SQLite and PostgreSQL via
:mod:`i4g.store.sql` session factories.  The legacy raw-``sqlite3`` class
was removed in the Store Consolidation sprint (WS-3 / D16).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from i4g.store import sql as sql_schema
from i4g.store.sql import (
    METADATA,
    dialect_insert,
)
from i4g.store.sql import session_factory as build_session_factory

if TYPE_CHECKING:  # pragma: no cover - import used only for type hints
    from i4g.reports.bundle_builder import DossierPlan


class DossierQueueStore:
    """Persists DossierPlan payloads for downstream agent execution.

    Accepts either a ``db_path`` (convenience for local SQLite) or a
    pre-configured ``session_factory``.
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
            resolved.parent.mkdir(parents=True, exist_ok=True)
            engine = sa.create_engine(
                f"sqlite:///{resolved}",
                connect_args={"check_same_thread": False, "timeout": 30},
                future=True,
            )
            self._session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
        else:
            self._session_factory = build_session_factory()

        # Auto-create tables only for SQLite (local dev convenience).
        # PostgreSQL schema is managed exclusively by Alembic migrations.
        with self._session_factory() as session:
            if session.bind.dialect.name == "sqlite":
                METADATA.create_all(session.connection())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enqueue_plan(self, plan: DossierPlan, *, priority: str = "normal") -> str:
        """Insert or replace a dossier plan in the queue."""

        now = datetime.now(UTC)
        payload = json.dumps(plan.to_dict(), sort_keys=True)

        with self._session_factory() as session:
            stmt = dialect_insert(session, sql_schema.dossier_queue).values(
                plan_id=plan.plan_id,
                status="pending",
                priority=priority,
                payload=payload,
                queued_at=now,
                updated_at=now,
                warnings=None,
                error=None,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["plan_id"],
                set_={
                    "status": "pending",
                    "priority": stmt.excluded.priority,
                    "payload": stmt.excluded.payload,
                    "queued_at": stmt.excluded.queued_at,
                    "updated_at": stmt.excluded.updated_at,
                    "warnings": None,
                    "error": None,
                },
            )
            session.execute(stmt)
            session.commit()

        return plan.plan_id

    def list_pending(self, *, limit: int = 25) -> list[dict[str, Any]]:
        """Return pending queue entries along with their serialized plans."""

        stmt = (
            sa.select(sql_schema.dossier_queue)
            .where(sql_schema.dossier_queue.c.status == "pending")
            .order_by(sql_schema.dossier_queue.c.queued_at.asc())
            .limit(limit)
        )

        with self._session_factory() as session:
            rows = session.execute(stmt).fetchall()

        return [self._row_to_dict(row) for row in rows]

    def list_plans(self, *, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """Return queue entries filtered by ``status`` (or all entries when omitted)."""

        stmt = sa.select(sql_schema.dossier_queue).limit(limit).order_by(sql_schema.dossier_queue.c.updated_at.desc())
        if status:
            stmt = stmt.where(sql_schema.dossier_queue.c.status == status)

        with self._session_factory() as session:
            rows = session.execute(stmt).fetchall()

        return [self._row_to_dict(row) for row in rows]

    def get_plan(self, plan_id: str) -> dict[str, Any] | None:
        """Return a single queue entry regardless of status."""

        stmt = sa.select(sql_schema.dossier_queue).where(sql_schema.dossier_queue.c.plan_id == plan_id)

        with self._session_factory() as session:
            row = session.execute(stmt).fetchone()

        if not row:
            return None
        return self._row_to_dict(row)

    def mark_complete(self, plan_id: str, *, warnings: Sequence[str] | None = None) -> None:
        """Mark a queued plan as completed and persist optional warnings."""
        self._update_status(plan_id, status="completed", warnings=warnings)

    def mark_failed(self, plan_id: str, error: str) -> None:
        """Mark a queued plan as failed with an error message."""
        self._update_status(plan_id, status="failed", error=error)

    def reset(self, plan_id: str) -> None:
        """Return a leased plan to the pending state (used for dry runs)."""
        self._update_status(plan_id, status="pending", warnings=None)

    def lease_next(self) -> dict[str, Any] | None:
        """Atomically lease the next pending entry for processing."""

        now = datetime.now(UTC)

        with self._session_factory() as session:
            dialect = session.get_bind().dialect.name

            if dialect == "postgresql":
                # Postgres: atomic CTE with FOR UPDATE SKIP LOCKED
                subq = (
                    sa.select(sql_schema.dossier_queue.c.plan_id)
                    .where(sql_schema.dossier_queue.c.status == "pending")
                    .order_by(sql_schema.dossier_queue.c.queued_at.asc())
                    .limit(1)
                    .with_for_update(skip_locked=True)
                    .scalar_subquery()
                )
                stmt = (
                    sa.update(sql_schema.dossier_queue)
                    .where(sql_schema.dossier_queue.c.plan_id == subq)
                    .values(status="leased", updated_at=now)
                    .returning(sql_schema.dossier_queue)
                )
                row = session.execute(stmt).fetchone()
            else:
                # SQLite: SELECT + UPDATE inside the same transaction
                row = session.execute(
                    sa.select(sql_schema.dossier_queue)
                    .where(sql_schema.dossier_queue.c.status == "pending")
                    .order_by(sql_schema.dossier_queue.c.queued_at.asc())
                    .limit(1)
                ).fetchone()
                if row:
                    session.execute(
                        sa.update(sql_schema.dossier_queue)
                        .where(sql_schema.dossier_queue.c.plan_id == row.plan_id)
                        .values(status="leased", updated_at=now)
                    )

            session.commit()

        if not row:
            return None
        return self._row_to_dict(row)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _update_status(
        self,
        plan_id: str,
        *,
        status: str,
        error: str | None = None,
        warnings: Sequence[str] | None = None,
    ) -> None:
        now = datetime.now(UTC)
        warnings_payload = json.dumps(list(warnings)) if warnings is not None else None

        values: dict[str, Any] = {"status": status, "updated_at": now}
        if error is not None:
            values["error"] = error
        elif status == "pending":
            values["error"] = None

        if warnings is not None:
            values["warnings"] = warnings_payload
        elif status == "pending":
            values["warnings"] = None

        stmt = sa.update(sql_schema.dossier_queue).where(sql_schema.dossier_queue.c.plan_id == plan_id).values(**values)

        with self._session_factory() as session:
            session.execute(stmt)
            session.commit()

    def _row_to_dict(self, row: Any) -> dict[str, Any]:
        """Convert a SQLAlchemy Row to a JSON-friendly dict."""
        payload_raw = row.payload
        payload = json.loads(payload_raw) if payload_raw else {}
        warnings_raw = row.warnings

        queued = row.queued_at
        updated = row.updated_at
        # Normalise timestamps to ISO strings for API consumers
        if hasattr(queued, "isoformat"):
            queued = queued.isoformat()
        if hasattr(updated, "isoformat"):
            updated = updated.isoformat()

        return {
            "plan_id": row.plan_id,
            "status": row.status,
            "priority": row.priority,
            "payload": payload,
            "queued_at": queued,
            "updated_at": updated,
            "warnings": json.loads(warnings_raw) if warnings_raw else [],
            "error": row.error,
        }


# Backward-compatible alias
SqlAlchemyDossierQueueStore = DossierQueueStore
