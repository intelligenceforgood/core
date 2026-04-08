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

_DEFAULT_LEADERBOARD_WEIGHTS = {
    "accuracy": 0.40,
    "throughput": 0.35,
    "quality": 0.25,
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

    def get_extended_summary(self, engagement_id: str) -> dict[str, Any] | None:
        """Return engagement summary with classification distribution and analyst count."""
        base = self.get_summary(engagement_id)
        if base is None:
            return None

        c = sql_schema.cases
        ra = sql_schema.review_actions
        rq = sql_schema.review_queue
        eng = sql_schema.engagements

        with self._session_factory() as session:
            # Classification distribution
            cls_rows = session.execute(
                sa.select(c.c.classification, sa.func.count().label("cnt"))
                .where(c.c.engagement_id == engagement_id)
                .where(c.c.classification.isnot(None))
                .group_by(c.c.classification)
                .order_by(sa.desc("cnt"))
            ).fetchall()
            classification_distribution = {row.classification: row.cnt for row in cls_rows}

            top_classifications = [row.classification for row in cls_rows[:5]]

            # Analyst count: distinct actors on review actions for cases in this engagement
            analyst_count = (
                session.execute(
                    sa.select(sa.func.count(sa.distinct(ra.c.actor)))
                    .select_from(ra.join(rq, ra.c.review_id == rq.c.review_id).join(c, rq.c.case_id == c.c.case_id))
                    .where(c.c.engagement_id == engagement_id)
                    .where(ra.c.actor.isnot(None))
                ).scalar()
                or 0
            )

            # Days elapsed / remaining
            eng_row = session.execute(
                sa.select(eng.c.starts_at, eng.c.ends_at).where(eng.c.engagement_id == engagement_id)
            ).first()
            now = datetime.now(UTC)
            days_elapsed = None
            days_remaining = None
            if eng_row and eng_row.starts_at:
                starts = eng_row.starts_at
                if starts.tzinfo is None:
                    starts = starts.replace(tzinfo=UTC)
                days_elapsed = max((now - starts).days, 0)
            if eng_row and eng_row.ends_at:
                ends = eng_row.ends_at
                if ends.tzinfo is None:
                    ends = ends.replace(tzinfo=UTC)
                days_remaining = max((ends - now).days, 0)

            # Average review time in hours from review actions
            avg_review_time_hours = None
            stats_table = sql_schema.engagement_analyst_stats
            avg_row = session.execute(
                sa.select(sa.func.avg(stats_table.c.avg_review_time_seconds))
                .where(stats_table.c.engagement_id == engagement_id)
                .where(stats_table.c.avg_review_time_seconds.isnot(None))
            ).scalar()
            if avg_row is not None:
                avg_review_time_hours = round(float(avg_row) / 3600.0, 1)

        return {
            **base,
            "classification_distribution": classification_distribution,
            "top_classifications": top_classifications,
            "analyst_count": analyst_count,
            "days_elapsed": days_elapsed,
            "days_remaining": days_remaining,
            "avg_review_time_hours": avg_review_time_hours,
        }

    def get_leaderboard(
        self,
        engagement_id: str,
        *,
        weights: dict[str, float] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]] | None:
        """Return ranked analyst leaderboard for an engagement.

        Returns None if the engagement does not exist.
        """
        if self.get(engagement_id) is None:
            return None

        w = weights or _DEFAULT_LEADERBOARD_WEIGHTS
        stats_table = sql_schema.engagement_analyst_stats

        with self._session_factory() as session:
            rows = session.execute(
                sa.select(stats_table)
                .where(stats_table.c.engagement_id == engagement_id)
                .order_by(stats_table.c.cases_reviewed.desc())
                .limit(limit)
            ).fetchall()

        if not rows:
            return []

        # Compute composite scores and rank
        entries = []
        max_reviewed = max(r.cases_reviewed for r in rows) or 1
        for row in rows:
            accuracy = float(row.classification_accuracy or 0)
            throughput = row.cases_reviewed / max_reviewed
            risk_mae = float(row.risk_score_mae or 0)
            quality = max(1.0 - (risk_mae / 100.0), 0.0) if row.risk_score_mae is not None else 0.0

            composite = (
                w.get("accuracy", 0.40) * accuracy
                + w.get("throughput", 0.35) * throughput
                + w.get("quality", 0.25) * quality
            )

            entries.append(
                {
                    "analyst_email": row.analyst_email,
                    "cases_reviewed": row.cases_reviewed,
                    "avg_review_time_seconds": (
                        float(row.avg_review_time_seconds) if row.avg_review_time_seconds else None
                    ),
                    "classification_accuracy": accuracy,
                    "risk_score_mae": float(row.risk_score_mae) if row.risk_score_mae is not None else None,
                    "actions_logged": row.actions_logged,
                    "last_activity_at": row.last_activity_at,
                    "composite_score": round(composite * 100, 1),
                }
            )

        # Sort by composite_score descending, assign rank
        entries.sort(key=lambda e: e["composite_score"], reverse=True)
        for i, entry in enumerate(entries, 1):
            entry["rank"] = i

        return entries
