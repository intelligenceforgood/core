"""
ReviewStore: Manages the analyst review queue and action logs.

This module provides a unified interface for tracking cases that require analyst
review, supporting both SQLite (Local) and PostgreSQL (Dev/Prod) via SQLAlchemy.

Key features:
- Review queue management (enqueue, update status, list)
- Action logging (audit trail)
- Unified behavior across environments
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from i4g.settings import get_settings
from i4g.store import sql as sql_schema
from i4g.store.sql import session_factory as default_session_factory

SETTINGS = get_settings()


def _iso_timestamp(value: Optional[datetime]) -> str:
    """Return an ISO-8601 string, defaulting to UTC now when value is None."""
    dt = value or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _summarize_dashboard_rows(
    rows: Iterable[Any],
    limit: int,
    status_filter: Optional[str],
    priority_filter: Optional[str],
    queue_filter: Optional[str],
    due_date_filter: Optional[str],
) -> Dict[str, Any]:
    """Shared logic for aggregating dashboard metrics from review queue rows."""
    summary = {
        "active": 0,
        "dueToday": 0,
        "pendingReview": 0,
        "escalations": 0,
    }
    cases_list = []

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    queues_map = {
        "Rapid Response": 0,
        "Policy Review": 0,
        "Financial Intelligence": 0,
        "NGO Coordination": 0,
    }

    for r in rows:
        # Normalize row access (sqlite3.Row vs SQLAlchemy Row)
        d_row = r._mapping if hasattr(r, "_mapping") else dict(r)

        meta = {}
        raw_meta = d_row.get("metadata")
        if raw_meta:
            if isinstance(raw_meta, str):
                try:
                    meta = json.loads(raw_meta)
                except Exception:
                    pass
            elif isinstance(raw_meta, dict):
                meta = raw_meta

        row_queue = meta.get("queue")

        ui_status = d_row.get("status")
        current_priority = d_row.get("priority")

        # 1. Update Counts
        summary["active"] += 1

        if d_row.get("status") == "new":
            summary["pendingReview"] += 1

        if current_priority in ("high", "critical"):
            summary["escalations"] += 1

        due_at = meta.get("dueAt")
        if due_at and due_at[:10] <= today_str:
            summary["dueToday"] += 1

        if row_queue and row_queue in queues_map:
            queues_map[row_queue] += 1

        # 2. Build Case List (Apply Filters)
        if status_filter:
            statuses = status_filter.split(",")
            if ui_status not in statuses:
                continue
        if priority_filter:
            priorities = priority_filter.split(",")
            if current_priority not in priorities:
                continue
        if queue_filter and row_queue != queue_filter:
            continue

        if due_date_filter == "today":
            if not (due_at and due_at[:10] <= today_str):
                continue

        if len(cases_list) < limit:
            tags = []
            raw_tags = d_row.get("tags")
            if raw_tags:
                if isinstance(raw_tags, str):
                    try:
                        tags = json.loads(raw_tags)
                    except:
                        tags = []
                elif isinstance(raw_tags, list):
                    tags = raw_tags

            # Handle timestamps (str or datetime)
            last_updated = d_row.get("last_updated") or d_row.get("queued_at")
            if isinstance(last_updated, datetime):
                updated_at = _iso_timestamp(last_updated)
            else:
                updated_at = str(last_updated) if last_updated else ""

            cases_list.append(
                {
                    "id": d_row["case_id"],
                    "title": meta.get("title", f"Case {d_row['case_id']}"),
                    "priority": current_priority,
                    "status": ui_status,
                    "updatedAt": updated_at,
                    "assignee": d_row.get("assigned_to"),
                    "queue": row_queue or "General",
                    "tags": tags,
                    "progress": meta.get("progress", 0),
                    "dueAt": due_at,
                }
            )

    queues_list = [
        {
            "id": "queue-rapid",
            "name": "Rapid Response",
            "description": "Emergent escalations",
            "count": queues_map["Rapid Response"],
        },
        {
            "id": "queue-policy",
            "name": "Policy Review",
            "description": "Policy adjudication",
            "count": queues_map["Policy Review"],
        },
        {
            "id": "queue-fin",
            "name": "Financial Intelligence",
            "description": "Payment analysis",
            "count": queues_map["Financial Intelligence"],
        },
        {
            "id": "queue-ngo",
            "name": "NGO Coordination",
            "description": "Partner intake",
            "count": queues_map["NGO Coordination"],
        },
    ]

    return {
        "summary": summary,
        "cases": cases_list,
        "queues": queues_list,
    }


class ReviewStore:
    """SQLAlchemy-backed review queue and audit logger.

    Unified implementation for both SQLite and PostgreSQL.
    """

    def __init__(self, session_factory: sessionmaker | None = None) -> None:
        self._session_factory = session_factory or default_session_factory()

    def get_extended_case(self, case_id: str) -> Optional[Dict[str, Any]]:
        """Fetch full case details including timeline and scam record data."""
        rq = sql_schema.review_queue
        sr = sql_schema.scam_records
        ra = sql_schema.review_actions

        stmt = (
            sa.select(
                rq.c.review_id,
                rq.c.case_id,
                rq.c.status,
                rq.c.priority,
                rq.c.assigned_to,
                rq.c.tags,
                rq.c.queued_at,
                rq.c.last_updated,
                rq.c.notes,
                rq.c.classification_result,
                sr.c.text,
                sr.c.entities,
                sr.c.classification,
                sr.c.confidence,
                sr.c.metadata,
            )
            .select_from(rq.join(sr, rq.c.case_id == sr.c.case_id, isouter=True))
            .where(rq.c.case_id == case_id)
        )

        with self._session_factory() as session:
            row = session.execute(stmt).first()
            if not row:
                return None

            data = dict(row._mapping)

            # Normalize timestamps to ISO strings for parity
            for field in ["queued_at", "last_updated"]:
                val = data.get(field)
                if isinstance(val, datetime):
                    data[field] = _iso_timestamp(val)

            # Fetch Timeline
            actions = session.execute(
                sa.select(
                    ra.c.action_id,
                    ra.c.actor,
                    ra.c.action,
                    ra.c.payload,
                    ra.c.created_at,
                )
                .where(ra.c.review_id == data["review_id"])
                .order_by(ra.c.created_at.desc())
            ).all()

            data["timeline"] = []
            for action in actions:
                a_dict = dict(action._mapping)
                ts = a_dict.get("created_at")
                if isinstance(ts, datetime):
                    a_dict["created_at"] = _iso_timestamp(ts)
                data["timeline"].append(a_dict)

            return data

    def get_dashboard_summary(
        self,
        limit: int = 50,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        queue: Optional[str] = None,
        due_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Aggregate summary statistics and recent cases for the dashboard."""

        rq = sql_schema.review_queue
        sr = sql_schema.scam_records

        # Fetch all active items to aggregate counts correctly regardless of filters
        stmt = (
            sa.select(
                rq.c.case_id,
                rq.c.status,
                rq.c.priority,
                rq.c.assigned_to,
                rq.c.tags,
                rq.c.last_updated,
                rq.c.queued_at,
                sr.c.metadata,
            )
            .select_from(rq.join(sr, rq.c.case_id == sr.c.case_id, isouter=True))
            .where(sa.not_(rq.c.status.in_(["closed", "accepted", "rejected"])))
            .order_by(rq.c.last_updated.desc())
        )

        with self._session_factory() as session:
            rows = session.execute(stmt).all()

        return _summarize_dashboard_rows(
            rows,
            limit=limit,
            status_filter=status,
            priority_filter=priority,
            queue_filter=queue,
            due_date_filter=due_date,
        )

    def get_queue(self, status: str = "new", limit: int = 25) -> List[Dict[str, Any]]:
        with self._session_factory() as session:
            rows = session.execute(
                sa.select(sql_schema.review_queue)
                .where(sql_schema.review_queue.c.status == status)
                .order_by(sql_schema.review_queue.c.queued_at.asc())
                .limit(limit)
            ).all()
            return [dict(r._mapping) for r in rows]

    def get_review(self, review_id: str) -> Optional[Dict[str, Any]]:
        with self._session_factory() as session:
            row = session.execute(
                sa.select(sql_schema.review_queue).where(sql_schema.review_queue.c.review_id == review_id)
            ).first()
            return dict(row._mapping) if row else None

    def get_cases(self, case_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        normalized = list({str(cid).strip() for cid in case_ids if cid and str(cid).strip()})
        if not normalized:
            return {}

        with self._session_factory() as session:
            rows = session.execute(
                sa.select(sql_schema.review_queue).where(sql_schema.review_queue.c.case_id.in_(normalized))
            ).all()
            return {str(row.case_id): dict(row._mapping) for row in rows}

    def enqueue_case(
        self,
        case_id: str,
        priority: str = "medium",
        classification_result: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
    ) -> str:
        """Enqueue a case for review."""
        return self.upsert_queue_entry(
            review_id=None,
            case_id=case_id,
            status="new",
            queued_at=datetime.now(timezone.utc),
            priority=priority,
            classification_result=classification_result,
            tags=tags,
        )

    def update_status(self, review_id: str, status: str, notes: Optional[str] = None) -> None:
        now = datetime.now(timezone.utc)
        with self._session_factory() as session:
            stmt = (
                sa.update(sql_schema.review_queue)
                .where(sql_schema.review_queue.c.review_id == review_id)
                .values(status=status, notes=notes, last_updated=now)
            )
            session.execute(stmt)
            session.commit()

    def upsert_queue_entry(
        self,
        *,
        review_id: Optional[str],
        case_id: str,
        status: str,
        queued_at: datetime,
        priority: str = "medium",
        last_updated: Optional[datetime] = None,
        assigned_to: Optional[str] = None,
        notes: Optional[str] = None,
        classification_result: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
    ) -> str:
        normalized_review_id = review_id or str(uuid.uuid4())
        last_updated = last_updated or queued_at

        # Attempt generic upsert logic to support both SQLite and Postgres
        # Note: We rely on SQLAlchemy's dialect support or explicit branching if needed.
        # Simple implementations often use sa.dialects.postgresql.insert for PG.
        # For simplicity in this unified store, we can use the PG dialect insert
        # if the underlying engine supports it (modern SQLite often tolerates it via SQLAlchemy).

        with self._session_factory() as session:
            headers = {
                "review_id": normalized_review_id,
                "case_id": case_id,
                "queued_at": queued_at,
                "priority": priority,
                "status": status,
                "assigned_to": assigned_to,
                "notes": notes,
                "last_updated": last_updated,
            }
            if classification_result is not None:
                headers["classification_result"] = classification_result
            if tags is not None:
                headers["tags"] = tags

            stmt = sa.dialects.postgresql.insert(sql_schema.review_queue).values(**headers)

            update_dict = {
                "case_id": stmt.excluded.case_id,
                "queued_at": stmt.excluded.queued_at,
                "priority": stmt.excluded.priority,
                "status": stmt.excluded.status,
                "assigned_to": stmt.excluded.assigned_to,
                "notes": stmt.excluded.notes,
                "last_updated": stmt.excluded.last_updated,
            }
            if classification_result is not None:
                update_dict["classification_result"] = stmt.excluded.classification_result
            if tags is not None:
                update_dict["tags"] = stmt.excluded.tags

            stmt = stmt.on_conflict_do_update(
                index_elements=["review_id"],
                set_=update_dict,
            )
            session.execute(stmt)
            session.commit()
        return normalized_review_id

    def ensure_placeholder_review(self, review_id: str, case_id: str) -> None:
        """Ensure a placeholder review exists for audit logging purposes."""
        now = datetime.now(timezone.utc)
        with self._session_factory() as session:
            try:
                session.execute(
                    sa.dialects.postgresql.insert(sql_schema.review_queue)
                    .values(
                        review_id=review_id,
                        case_id=case_id,
                        queued_at=now,
                        priority="medium",
                        status="new",
                        last_updated=now,
                    )
                    .on_conflict_do_nothing()
                )
                session.commit()
            except Exception:
                # Ignore errors if it already exists or race condition
                pass

    def log_action(
        self,
        review_id: str,
        action: str,
        actor: str = "system",
        payload: Optional[Dict[str, Any]] = None,
    ) -> str:
        action_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        with self._session_factory() as session:
            # Special handling for search history: ensure the "search" review exists
            if review_id == "search":
                try:
                    # Try to insert the dummy search review if it doesn't exist
                    session.execute(
                        sa.dialects.postgresql.insert(sql_schema.review_queue)
                        .values(
                            review_id="search",
                            case_id="search_placeholder",
                            queued_at=now,
                            priority="medium",
                            status="closed",
                            last_updated=now,
                        )
                        .on_conflict_do_nothing()
                    )
                except Exception:
                    # Ignore errors if it already exists or race condition
                    pass

            stmt = sa.insert(sql_schema.review_actions).values(
                action_id=action_id,
                review_id=review_id,
                actor=actor,
                action=action,
                payload=payload,
                created_at=now,
            )
            session.execute(stmt)
            session.commit()
        return action_id

    def get_recent_actions(self, action: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        with self._session_factory() as session:
            query = sa.select(sql_schema.review_actions)
            if action:
                query = query.where(sql_schema.review_actions.c.action == action)
            query = query.order_by(sql_schema.review_actions.c.created_at.desc()).limit(limit)
            rows = session.execute(query).all()
            return [dict(r._mapping) for r in rows]

    def get_actions(self, review_id: str) -> List[Dict[str, Any]]:
        with self._session_factory() as session:
            rows = session.execute(
                sa.select(sql_schema.review_actions)
                .where(sql_schema.review_actions.c.review_id == review_id)
                .order_by(sql_schema.review_actions.c.created_at.asc())
            ).all()
            return [dict(r._mapping) for r in rows]

    def upsert_saved_search(
        self,
        name: str,
        params: Dict[str, Any],
        owner: Optional[str] = None,
        search_id: Optional[str] = None,
        favorite: bool = False,
        tags: Optional[List[str]] = None,
    ) -> str:
        sid = search_id or str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        tags_json = tags or []

        with self._session_factory() as session:
            stmt = sa.dialects.postgresql.insert(sql_schema.saved_searches).values(
                search_id=sid,
                name=name,
                owner=owner,
                params=params,
                created_at=now,
                favorite=favorite,
                tags=tags_json,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["search_id"],
                set_={
                    "name": stmt.excluded.name,
                    "owner": stmt.excluded.owner,
                    "params": stmt.excluded.params,
                    "tags": stmt.excluded.tags,
                    "favorite": stmt.excluded.favorite,
                },
            )
            session.execute(stmt)
            session.commit()
        return sid

    def list_saved_searches(self, owner: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        with self._session_factory() as session:
            query = sa.select(sql_schema.saved_searches)
            if owner:
                query = query.where(
                    sa.or_(
                        sql_schema.saved_searches.c.owner == owner,
                        sql_schema.saved_searches.c.owner.is_(None),
                    )
                )
            query = query.order_by(
                sql_schema.saved_searches.c.favorite.desc(),
                sql_schema.saved_searches.c.created_at.desc(),
            ).limit(limit)
            rows = session.execute(query).all()
            return [dict(r._mapping) for r in rows]

    def list_searches(self, owner: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._session_factory() as session:
            query = sa.select(sql_schema.saved_searches)
            if owner:
                query = query.where(sql_schema.saved_searches.c.owner == owner)
            query = query.order_by(sql_schema.saved_searches.c.created_at.desc())
            rows = session.execute(query).all()
            return [dict(r._mapping) for r in rows]

    def get_search(self, search_id: str) -> Optional[Dict[str, Any]]:
        with self._session_factory() as session:
            row = session.execute(
                sa.select(sql_schema.saved_searches).where(sql_schema.saved_searches.c.search_id == search_id)
            ).first()
            return dict(row._mapping) if row else None

    def delete_search(self, search_id: str) -> bool:
        with self._session_factory() as session:
            result = session.execute(
                sa.delete(sql_schema.saved_searches).where(sql_schema.saved_searches.c.search_id == search_id)
            )
            session.commit()
            return result.rowcount > 0

    def toggle_favorite(self, search_id: str, favorite: bool) -> bool:
        with self._session_factory() as session:
            result = session.execute(
                sa.update(sql_schema.saved_searches)
                .where(sql_schema.saved_searches.c.search_id == search_id)
                .values(favorite=favorite)
            )
            session.commit()
            return result.rowcount > 0

    def update_saved_search(
        self,
        search_id: str,
        name: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
    ) -> bool:
        values = {}
        if name is not None:
            values["name"] = name
        if params is not None:
            values["params"] = params
        if tags is not None:
            values["tags"] = tags

        if not values:
            return False

        with self._session_factory() as session:
            result = session.execute(
                sa.update(sql_schema.saved_searches)
                .where(sql_schema.saved_searches.c.search_id == search_id)
                .values(**values)
            )
            session.commit()
            return result.rowcount > 0

    def bulk_tag_searches(self, search_ids: List[str], tags: List[str]) -> int:
        updated = 0
        for sid in search_ids:
            search = self.get_search(sid)
            if not search:
                continue
            current_tags = search.get("tags") or []
            if not isinstance(current_tags, list):
                current_tags = []

            new_tags = list(set(current_tags + tags))
            if self.update_saved_search(sid, tags=new_tags):
                updated += 1
        return updated


# Alias for backward compatibility if needed, though factories.py is updated
SqlAlchemyReviewStore = ReviewStore
