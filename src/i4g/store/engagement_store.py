"""EngagementStore: CRUD and case assignment for engagements."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from i4g.store import sql as sql_schema
from i4g.store.sql import session_factory as default_session_factory

VALID_STATUSES = {"draft", "active", "completed", "archived"}

VALID_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"active", "draft"},
    "active": {"completed", "draft"},
    "completed": {"archived", "draft"},
    "archived": {"draft"},
}


class EngagementStore:
    """SQLAlchemy-backed engagement CRUD and case assignment."""

    def __init__(self, session_factory: sessionmaker | None = None) -> None:
        self._session_factory = session_factory or default_session_factory()

    def create(
        self,
        *,
        name: str,
        description: str | None = None,
        status: str = "draft",
        starts_at: datetime | None = None,
        ends_at: datetime | None = None,
        created_by: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new engagement and return its dict representation."""
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {status}")
        engagement_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        row = {
            "engagement_id": engagement_id,
            "name": name,
            "description": description,
            "status": status,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "created_by": created_by,
            "metadata": metadata,
            "created_at": now,
            "updated_at": now,
        }
        with self._session_factory() as session:
            session.execute(sa.insert(sql_schema.engagements).values(row))
            session.commit()
        return row

    def get(self, engagement_id: str) -> dict[str, Any] | None:
        """Return a single engagement by ID, or None if not found."""
        eng = sql_schema.engagements
        with self._session_factory() as session:
            result = session.execute(sa.select(eng).where(eng.c.engagement_id == engagement_id)).first()
            if result is None:
                return None
            return dict(result._mapping)

    def list(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List engagements, optionally filtered by status."""
        eng = sql_schema.engagements
        stmt = sa.select(eng).order_by(eng.c.created_at.desc()).limit(limit).offset(offset)
        if status:
            stmt = stmt.where(eng.c.status == status)
        with self._session_factory() as session:
            rows = session.execute(stmt).fetchall()
            return [dict(r._mapping) for r in rows]

    def update(
        self,
        engagement_id: str,
        **fields: Any,
    ) -> dict[str, Any] | None:
        """Update engagement fields. Returns updated engagement or None if not found."""
        existing = self.get(engagement_id)
        if existing is None:
            return None

        # Validate status transition if status is being changed
        new_status = fields.get("status")
        if new_status is not None:
            if new_status not in VALID_STATUSES:
                raise ValueError(f"Invalid status: {new_status}")
            current_status = existing["status"]
            if new_status != current_status and new_status not in VALID_TRANSITIONS.get(current_status, set()):
                raise ValueError(f"Invalid transition: {current_status} → {new_status}")

        allowed = {"name", "description", "status", "starts_at", "ends_at", "metadata"}
        update_vals = {k: v for k, v in fields.items() if k in allowed}
        if not update_vals:
            return existing

        update_vals["updated_at"] = datetime.now(UTC)
        eng = sql_schema.engagements
        with self._session_factory() as session:
            session.execute(sa.update(eng).where(eng.c.engagement_id == engagement_id).values(**update_vals))
            session.commit()
        return self.get(engagement_id)

    def archive(self, engagement_id: str) -> dict[str, Any] | None:
        """Soft-delete: transition to archived status."""
        return self.update(engagement_id, status="archived")

    def assign_cases(self, engagement_id: str, case_ids: list[str]) -> int:
        """Assign cases to an engagement. Returns count of cases updated."""
        if not case_ids:
            return 0
        c = sql_schema.cases
        with self._session_factory() as session:
            result = session.execute(
                sa.update(c)
                .where(c.c.case_id.in_(case_ids))
                .values(engagement_id=engagement_id, updated_at=datetime.now(UTC))
            )
            session.commit()
            return result.rowcount

    def remove_cases(self, engagement_id: str, case_ids: list[str]) -> int:
        """Remove case assignments from an engagement. Returns count updated."""
        if not case_ids:
            return 0
        c = sql_schema.cases
        with self._session_factory() as session:
            result = session.execute(
                sa.update(c)
                .where(c.c.case_id.in_(case_ids))
                .where(c.c.engagement_id == engagement_id)
                .values(engagement_id=None, updated_at=datetime.now(UTC))
            )
            session.commit()
            return result.rowcount

    def get_summary(self, engagement_id: str) -> dict[str, Any] | None:
        """Return engagement summary stats: case count, reviewed, completion %."""
        existing = self.get(engagement_id)
        if existing is None:
            return None

        c = sql_schema.cases
        rq = sql_schema.review_queue

        with self._session_factory() as session:
            # Total cases in this engagement
            case_count = (
                session.execute(
                    sa.select(sa.func.count()).select_from(c).where(c.c.engagement_id == engagement_id)
                ).scalar()
                or 0
            )

            # Reviewed cases: those with a review_queue entry with status in completed states
            reviewed_count = 0
            if case_count > 0:
                reviewed_count = (
                    session.execute(
                        sa.select(sa.func.count(sa.distinct(rq.c.case_id)))
                        .select_from(rq.join(c, rq.c.case_id == c.c.case_id))
                        .where(c.c.engagement_id == engagement_id)
                        .where(rq.c.status.in_(["accepted", "rejected", "closed"]))
                    ).scalar()
                    or 0
                )

        remaining = case_count - reviewed_count
        completion_pct = round((reviewed_count / case_count * 100), 1) if case_count > 0 else 0.0

        return {
            **existing,
            "case_count": case_count,
            "cases_reviewed": reviewed_count,
            "cases_remaining": remaining,
            "review_completion_pct": completion_pct,
        }
