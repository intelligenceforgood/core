"""
ReviewStore: Manages the analyst review queue and action logs.

This module provides a unified interface for tracking cases that require analyst
review, supporting both SQLite (Local) and PostgreSQL (Dev/Prod) via SQLAlchemy.

Key features:
- Review queue management (enqueue, update status, list)
- Action logging (audit trail)
- Unified behavior across environments
"""

import contextlib
import json
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from i4g.store import sql as sql_schema
from i4g.store.sql import session_factory as default_session_factory


def _iso_timestamp(value: datetime | None) -> str:
    """Return an ISO-8601 string, defaulting to UTC now when value is None."""
    dt = value or datetime.now(UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


def _summarize_dashboard_rows(
    rows: Iterable[Any],
    limit: int,
    status_filter: str | None,
    priority_filter: str | None,
    queue_filter: str | None,
    due_date_filter: str | None,
) -> dict[str, Any]:
    """Shared logic for aggregating dashboard metrics from review queue rows."""
    summary = {
        "active": 0,
        "dueToday": 0,
        "pendingReview": 0,
        "escalations": 0,
    }
    cases_list = []

    today_str = datetime.now(UTC).strftime("%Y-%m-%d")

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
                with contextlib.suppress(Exception):
                    meta = json.loads(raw_meta)
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

        if due_date_filter == "today" and not (due_at and due_at[:10] <= today_str):
            continue

        if len(cases_list) < limit:
            tags = []
            raw_tags = d_row.get("tags")
            if raw_tags:
                if isinstance(raw_tags, str):
                    try:
                        tags = json.loads(raw_tags)
                    except (json.JSONDecodeError, TypeError, ValueError):
                        tags = []
                elif isinstance(raw_tags, list):
                    tags = raw_tags

            # Handle timestamps (str or datetime)
            last_updated = d_row.get("last_updated") or d_row.get("queued_at")
            if isinstance(last_updated, datetime):
                updated_at = _iso_timestamp(last_updated)
            else:
                updated_at = str(last_updated) if last_updated else ""

            # Parse classification_result: prefer authoritative `cases` table
            # (maintained by the classification sweeper), fall back to review_queue.
            classification = d_row.get("cases_classification") or d_row.get("classification_result")
            if isinstance(classification, str):
                try:
                    classification = json.loads(classification)
                except Exception:
                    classification = None
            # Validate classification has required shape for SDK schema
            if isinstance(classification, dict):
                required_keys = {
                    "intent",
                    "channel",
                    "techniques",
                    "actions",
                    "persona",
                    "risk_score",
                    "taxonomy_version",
                }
                if not required_keys.issubset(classification.keys()):
                    classification = None

            case_entry: dict[str, Any] = {
                "id": d_row["case_id"],
                "title": meta.get("title", f"Case {d_row['case_id'][:8]}"),
                "priority": current_priority,
                "status": ui_status,
                "updatedAt": updated_at,
                "assignee": d_row.get("assigned_to"),
                "queue": row_queue or "General",
                "tags": tags,
                "progress": meta.get("progress", 0),
                "dueAt": due_at,
            }
            if classification is not None:
                case_entry["classification"] = classification
            cases_list.append(case_entry)

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

    def get_extended_case(self, case_id: str) -> dict[str, Any] | None:
        """Fetch full case details including timeline and scam record data."""
        rq = sql_schema.review_queue
        ra = sql_schema.review_actions
        c = sql_schema.cases

        stmt = (
            sa.select(
                rq.c.review_id,
                c.c.case_id,
                sa.func.coalesce(rq.c.status, sa.literal("new")).label("status"),
                sa.func.coalesce(rq.c.priority, sa.literal("medium")).label("priority"),
                rq.c.assigned_to,
                rq.c.tags,
                sa.func.coalesce(rq.c.queued_at, c.c.created_at).label("queued_at"),
                sa.func.coalesce(rq.c.last_updated, c.c.updated_at).label("last_updated"),
                rq.c.notes,
                c.c.classification_result,
                c.c.description.label("text"),
                c.c.classification,
                c.c.confidence,
                c.c.metadata,
                c.c.source_type,
            )
            .select_from(c.outerjoin(rq, rq.c.case_id == c.c.case_id))
            .where(c.c.case_id == case_id)
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

            # Fetch Timeline (only if the case has a review queue entry)
            data["timeline"] = []
            review_id = data.get("review_id")
            if review_id:
                actions = session.execute(
                    sa.select(
                        ra.c.action_id,
                        ra.c.actor,
                        ra.c.action,
                        ra.c.payload,
                        ra.c.created_at,
                    )
                    .where(ra.c.review_id == review_id)
                    .order_by(ra.c.created_at.desc())
                ).all()

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
        status: str | None = None,
        priority: str | None = None,
        queue: str | None = None,
        due_date: str | None = None,
        engagement_id: str | None = None,
    ) -> dict[str, Any]:
        """Aggregate summary statistics and recent cases for the dashboard."""

        rq = sql_schema.review_queue
        c = sql_schema.cases

        # Fetch all active items to aggregate counts correctly regardless of filters.
        # Classification is read from the authoritative `cases` table (maintained by
        # the classification sweeper) with a fallback to `review_queue` for seed data.
        stmt = (
            sa.select(
                rq.c.case_id,
                rq.c.status,
                rq.c.priority,
                rq.c.assigned_to,
                rq.c.tags,
                rq.c.last_updated,
                rq.c.queued_at,
                c.c.classification_result.label("cases_classification"),
                rq.c.classification_result,
                c.c.metadata,
            )
            .select_from(rq.join(c, rq.c.case_id == c.c.case_id, isouter=True))
            .where(sa.not_(rq.c.status.in_(["closed", "accepted", "rejected"])))
            .where(sa.not_(rq.c.case_id.like("system:%")))
            .order_by(rq.c.last_updated.desc())
        )

        if engagement_id is not None:
            stmt = stmt.where(c.c.engagement_id == engagement_id)

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

    def get_queue(self, status: str = "new", limit: int = 25) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            rows = session.execute(
                sa.select(sql_schema.review_queue)
                .where(sql_schema.review_queue.c.status == status)
                .order_by(sql_schema.review_queue.c.queued_at.asc())
                .limit(limit)
            ).all()
            return [dict(r._mapping) for r in rows]

    def get_review(self, review_id: str) -> dict[str, Any] | None:
        with self._session_factory() as session:
            row = session.execute(
                sa.select(sql_schema.review_queue).where(sql_schema.review_queue.c.review_id == review_id)
            ).first()
            return dict(row._mapping) if row else None

    def get_cases(self, case_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
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
        classification_result: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> str:
        """Enqueue a case for review."""
        return self.upsert_queue_entry(
            review_id=None,
            case_id=case_id,
            status="new",
            queued_at=datetime.now(UTC),
            priority=priority,
            classification_result=classification_result,
            tags=tags,
        )

    def update_status(self, review_id: str, status: str, notes: str | None = None) -> None:
        now = datetime.now(UTC)
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
        review_id: str | None,
        case_id: str,
        status: str,
        queued_at: datetime,
        priority: str = "medium",
        last_updated: datetime | None = None,
        assigned_to: str | None = None,
        notes: str | None = None,
        classification_result: dict[str, Any] | None = None,
        tags: list[str] | None = None,
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
        now = datetime.now(UTC)
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
        payload: dict[str, Any] | None = None,
    ) -> str:
        action_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        with self._session_factory() as session:
            # Special handling for search history: ensure the "search" review exists
            if review_id == "search":
                with contextlib.suppress(Exception):  # Ignore race conditions on insert
                    # Ensure the dummy search review exists
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

    def get_recent_actions(self, action: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            query = sa.select(sql_schema.review_actions)
            if action:
                query = query.where(sql_schema.review_actions.c.action == action)
            query = query.order_by(sql_schema.review_actions.c.created_at.desc()).limit(limit)
            rows = session.execute(query).all()
            return [dict(r._mapping) for r in rows]

    def get_actions(self, review_id: str) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            rows = session.execute(
                sa.select(sql_schema.review_actions)
                .where(sql_schema.review_actions.c.review_id == review_id)
                .order_by(sql_schema.review_actions.c.created_at.asc())
            ).all()
            return [dict(r._mapping) for r in rows]

    def apply_feedback_classification(
        self,
        review_id: str,
        corrected_classification: dict[str, Any],
    ) -> str | None:
        """Apply analyst-corrected classification to the underlying case.

        Updates both the review_queue classification_result and the cases table
        classification fields (classification, classification_result, risk_score,
        taxonomy_version, classification_status).

        Returns:
            The case_id that was updated, or None if the review was not found.
        """
        now = datetime.now(UTC)
        with self._session_factory() as session:
            case_id = _get_case_id_for_review(session, review_id)
            if not case_id:
                return None

            # Update review_queue
            session.execute(
                sa.update(sql_schema.review_queue)
                .where(sql_schema.review_queue.c.review_id == review_id)
                .values(classification_result=corrected_classification, last_updated=now)
            )

            # Derive top intent label
            top_label = "Unspecified"
            intents = corrected_classification.get("intent", [])
            if intents:
                sorted_intents = sorted(intents, key=lambda x: x.get("confidence", 0), reverse=True)
                top_label = sorted_intents[0].get("label", "Unspecified")

            risk_score = corrected_classification.get("risk_score", 0.0)
            taxonomy_version = corrected_classification.get("taxonomy_version", "1.0")

            # Update cases table
            session.execute(
                sa.update(sql_schema.cases)
                .where(sql_schema.cases.c.case_id == case_id)
                .values(
                    classification=top_label,
                    classification_result=corrected_classification,
                    classification_status="analyst_reviewed",
                    confidence=risk_score / 100.0,
                    risk_score=risk_score,
                    taxonomy_version=taxonomy_version,
                    updated_at=now,
                )
            )
            session.commit()
            return case_id

    def get_case_text(self, case_id: str) -> str | None:
        """Retrieve the primary source document text for a case."""
        with self._session_factory() as session:
            row = session.execute(
                sa.select(sql_schema.source_documents.c.text)
                .where(sql_schema.source_documents.c.case_id == case_id)
                .where(sql_schema.source_documents.c.text.is_not(None))
                .limit(1)
            ).first()
            return row.text if row else None

    def upsert_saved_search(
        self,
        name: str,
        params: dict[str, Any],
        owner: str | None = None,
        search_id: str | None = None,
        favorite: bool = False,
        tags: list[str] | None = None,
    ) -> str:
        sid = search_id or str(uuid.uuid4())
        now = datetime.now(UTC)
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

    def list_saved_searches(self, owner: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
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

    def list_searches(self, owner: str | None = None) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            query = sa.select(sql_schema.saved_searches)
            if owner:
                query = query.where(sql_schema.saved_searches.c.owner == owner)
            query = query.order_by(sql_schema.saved_searches.c.created_at.desc())
            rows = session.execute(query).all()
            return [dict(r._mapping) for r in rows]

    def get_search(self, search_id: str) -> dict[str, Any] | None:
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
        name: str | None = None,
        params: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        favorite: bool | None = None,
    ) -> bool:
        values: dict[str, Any] = {}
        if name is not None:
            values["name"] = name
        if params is not None:
            values["params"] = params
        if tags is not None:
            values["tags"] = tags
        if favorite is not None:
            values["favorite"] = favorite

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

    def bulk_tag_searches(self, search_ids: list[str], tags: list[str]) -> int:
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

    def bulk_update_tags(
        self,
        search_ids: list[str],
        add: list[str] | None = None,
        remove: list[str] | None = None,
        replace: list[str] | None = None,
    ) -> int:
        """Bulk update tags across multiple saved searches.

        Args:
            search_ids: IDs of saved searches to update.
            add: Tags to append (ignored when ``replace`` is set).
            remove: Tags to remove (ignored when ``replace`` is set).
            replace: When set, replaces all tags with this list.

        Returns:
            Number of records updated.
        """
        updated = 0
        for sid in search_ids:
            search = self.get_search(sid)
            if not search:
                continue

            if replace is not None:
                new_tags = list(replace)
            else:
                current_tags: list[str] = search.get("tags") or []
                if not isinstance(current_tags, list):
                    current_tags = []
                if remove:
                    current_tags = [t for t in current_tags if t not in remove]
                if add:
                    current_tags = current_tags + [t for t in add if t not in current_tags]
                new_tags = current_tags

            if self.update_saved_search(sid, tags=new_tags):
                updated += 1
        return updated

    # --- Alias methods --------------------------------------------------------
    # The API layer uses these names; keep thin wrappers for consistency.

    def get_saved_search(self, search_id: str) -> dict[str, Any] | None:
        """Alias for :meth:`get_search`."""
        return self.get_search(search_id)

    def delete_saved_search(self, search_id: str) -> bool:
        """Alias for :meth:`delete_search`."""
        return self.delete_search(search_id)

    def import_saved_search(
        self,
        record: dict[str, Any],
        owner: str | None = None,
    ) -> str:
        """Import a saved search definition from an export payload.

        Raises:
            ValueError: If name conflicts with existing search for same owner.
        """
        name = record.get("name", "Imported Search")
        params = record.get("params", {})
        tags = record.get("tags", [])
        favorite = record.get("favorite", False)

        # Check for name collision within same owner scope
        existing = self.list_saved_searches(owner=owner, limit=200)
        for entry in existing:
            if entry.get("name") == name:
                raise ValueError(f"duplicate_saved_search:{owner or ''}")

        return self.upsert_saved_search(
            name=name,
            params=params,
            owner=owner,
            favorite=favorite,
            tags=tags,
        )

    def clone_saved_search(self, search_id: str, target_owner: str | None = None) -> str:
        """Clone a saved search to a different owner (or shared scope).

        Args:
            search_id: Source search to clone.
            target_owner: New owner (``None`` for shared scope).

        Raises:
            ValueError: If source not found or name conflicts.
        """
        source = self.get_search(search_id)
        if not source:
            raise ValueError("saved_search_not_found")

        return self.import_saved_search(
            record={
                "name": source["name"],
                "params": source.get("params", {}),
                "tags": source.get("tags", []),
                "favorite": source.get("favorite", False),
            },
            owner=target_owner,
        )

    def list_tag_presets(self, owner: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """Derive tag presets by aggregating tags across saved searches.

        Returns a list of ``{tag, count}`` dicts ordered by frequency.
        """
        searches = self.list_saved_searches(owner=owner, limit=200)
        tag_counts: dict[str, int] = {}
        for entry in searches:
            tags = entry.get("tags") or []
            if isinstance(tags, list):
                for tag in tags:
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1

        presets = [{"tag": tag, "count": count} for tag, count in tag_counts.items()]
        presets.sort(key=lambda p: (-p["count"], p["tag"]))
        return presets[:limit]

    def get_reviews_by_case(self, case_id: str, limit: int = 5) -> list[dict[str, Any]]:
        """Return review queue entries for a given case ID."""
        with self._session_factory() as session:
            rows = session.execute(
                sa.select(sql_schema.review_queue)
                .where(sql_schema.review_queue.c.case_id == case_id)
                .order_by(sql_schema.review_queue.c.queued_at.desc())
                .limit(limit)
            ).all()
            return [dict(r._mapping) for r in rows]

    def list_dossier_candidates(
        self,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return review queue entries enriched with case metadata.

        Used by the dossier bundler to identify cases eligible for report
        generation. Joins ``review_queue`` with ``cases`` to provide
        loss band, geography, and cross-border indicators.
        """
        rq = sql_schema.review_queue
        c = sql_schema.cases

        query = (
            sa.select(
                rq.c.review_id,
                rq.c.case_id,
                rq.c.status,
                rq.c.priority,
                rq.c.queued_at,
                c.c.metadata.label("sr_metadata"),
            )
            .select_from(rq.outerjoin(c, rq.c.case_id == c.c.case_id))
            .order_by(rq.c.queued_at.desc())
            .limit(limit)
        )
        if status:
            query = query.where(rq.c.status == status)

        with self._session_factory() as session:
            rows = session.execute(query).all()

        results: list[dict[str, Any]] = []
        for row in rows:
            d = dict(row._mapping)
            meta = d.pop("sr_metadata", None) or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except (json.JSONDecodeError, TypeError, ValueError):
                    meta = {}

            loss_usd = meta.get("loss_amount_usd", 0)
            loss_band = _loss_band(loss_usd)
            victim = meta.get("victim_country", "")
            offender = meta.get("offender_country", "") or meta.get("scammer_country", "")
            jurisdiction = meta.get("jurisdiction", "")

            # Raw fields expected by BundleCandidateProvider._map_metric_rows
            d["loss_amount_usd"] = loss_usd
            d["accepted_at"] = d.get("queued_at")
            d["jurisdiction"] = jurisdiction or victim or "unknown"
            d["cross_border"] = 1 if (victim and offender and victim != offender) else 0

            # Derived analytics fields for dashboard/UI consumers
            d["loss_band"] = loss_band
            d["geo_bucket"] = victim or "Unknown"
            results.append(d)
        return results


def _loss_band(amount: float | int) -> str:
    """Map a USD loss amount to a human-readable band."""
    if amount <= 0:
        return "none"
    if amount < 10_000:
        return "<10k"
    if amount < 50_000:
        return "10k-50k"
    if amount < 100_000:
        return "50k-100k"
    if amount < 250_000:
        return "100k-250k"
    if amount < 1_000_000:
        return "250k-1M"
    return "1M+"


def _get_case_id_for_review(session: Any, review_id: str) -> str | None:
    """Look up the case_id associated with a review_id."""
    row = session.execute(
        sa.select(sql_schema.review_queue.c.case_id).where(sql_schema.review_queue.c.review_id == review_id)
    ).first()
    return row.case_id if row else None


# Alias for backward compatibility if needed, though factories.py is updated
SqlAlchemyReviewStore = ReviewStore
