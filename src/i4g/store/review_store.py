"""
ReviewStore: Manages the analyst review queue and action logs.

This module provides a lightweight, class-based interface over SQLite for
tracking cases that require analyst review. It is designed to integrate
with the StructuredStore for consistency and to support a future migration
to SQLAlchemy ORM.

Key features:
- Review queue management (enqueue, update status, list)
- Action logging (audit trail)
- Designed for analyst workflow integration (M6)

"""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from i4g.settings import get_settings
from i4g.store import sql as sql_schema
from i4g.store.sql import session_factory as default_session_factory

SETTINGS = get_settings()


class ReviewStore:
    """Lightweight SQLite-based review queue and audit logger."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        """
        Initialize the ReviewStore, creating tables if they do not exist.

        Args:
            db_path: Path to the SQLite database file.
        """
        resolved = Path(db_path) if db_path else Path(SETTINGS.storage.sqlite_path)
        if not resolved.is_absolute():
            resolved = (Path(SETTINGS.project_root) / resolved).resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = resolved
        self._init_tables()

    # -------------------------------------------------------------------------
    # Internal utilities
    # -------------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        """Return a SQLite connection with row factory set to dict."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self) -> None:
        """Create required tables if they do not exist."""
        conn = self._connect()
        cur = conn.cursor()

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS review_queue (
                review_id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL,
                queued_at TEXT NOT NULL,
                priority TEXT DEFAULT 'medium',
                status TEXT DEFAULT 'queued',
                assigned_to TEXT,
                notes TEXT,
                last_updated TEXT
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS review_actions (
                action_id TEXT PRIMARY KEY,
                review_id TEXT NOT NULL,
                actor TEXT,
                action TEXT,
                payload TEXT,
                created_at TEXT,
                FOREIGN KEY (review_id) REFERENCES review_queue (review_id)
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS saved_searches (
                search_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                owner TEXT,
                params TEXT,
                created_at TEXT,
                favorite INTEGER DEFAULT 0,
                tags TEXT DEFAULT '[]'
            )
            """
        )

        # Ensure favorite and tags columns exist for older schemas
        try:
            cur.execute("ALTER TABLE saved_searches ADD COLUMN favorite INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        try:
            cur.execute("ALTER TABLE saved_searches ADD COLUMN tags TEXT DEFAULT '[]'")
        except sqlite3.OperationalError:
            pass

        self._create_dossier_view(cur)
        conn.commit()
        conn.close()

    def _create_dossier_view(self, cursor: sqlite3.Cursor) -> None:
        """Create or refresh the dossier candidate metrics view."""

        view_sql = """
            CREATE VIEW IF NOT EXISTS dossier_candidate_metrics AS
            WITH raw AS (
                SELECT
                    rq.case_id AS case_id,
                    rq.status AS status,
                    COALESCE(rq.last_updated, rq.queued_at) AS accepted_at,
                    CAST(
                        COALESCE(
                            json_extract(sr.metadata, '$.loss_amount_usd'),
                            json_extract(sr.metadata, '$.loss_usd'),
                            json_extract(sr.metadata, '$.loss_amount'),
                            json_extract(sr.metadata, '$.loss')
                        ) AS REAL
                    ) AS loss_amount_usd,
                    COALESCE(
                        json_extract(sr.metadata, '$.jurisdiction'),
                        json_extract(sr.metadata, '$.victim_jurisdiction'),
                        json_extract(sr.metadata, '$.victim_state'),
                        json_extract(sr.metadata, '$.victim_country'),
                        'unknown'
                    ) AS jurisdiction,
                    UPPER(
                        COALESCE(
                            json_extract(sr.metadata, '$.victim_country'),
                            json_extract(sr.metadata, '$.victim_state'),
                            json_extract(sr.metadata, '$.jurisdiction_country')
                        )
                    ) AS victim_country,
                    UPPER(
                        COALESCE(
                            json_extract(sr.metadata, '$.offender_country'),
                            json_extract(sr.metadata, '$.scammer_country'),
                            json_extract(sr.metadata, '$.jurisdiction_country')
                        )
                    ) AS offender_country
                FROM review_queue rq
                LEFT JOIN scam_records sr ON sr.case_id = rq.case_id
            )
            SELECT
                case_id,
                status,
                accepted_at,
                loss_amount_usd,
                jurisdiction,
                victim_country,
                offender_country,
                CASE
                    WHEN victim_country IS NOT NULL
                         AND offender_country IS NOT NULL
                         AND victim_country <> offender_country
                    THEN 1
                    ELSE 0
                END AS cross_border,
                CASE
                    WHEN loss_amount_usd IS NULL THEN 'unknown'
                    WHEN loss_amount_usd >= 250000 THEN '250k-plus'
                    WHEN loss_amount_usd >= 100000 THEN '100k-250k'
                    WHEN loss_amount_usd >= 50000 THEN '50k-100k'
                    ELSE 'below-50k'
                END AS loss_band,
                CASE
                    WHEN jurisdiction IS NULL OR jurisdiction = '' THEN COALESCE(victim_country, 'unknown')
                    WHEN instr(jurisdiction, '-') > 0 THEN substr(jurisdiction, 1, instr(jurisdiction, '-') - 1)
                    ELSE jurisdiction
                END AS geo_bucket
            FROM raw
        """
        try:
            cursor.execute("DROP VIEW IF EXISTS dossier_candidate_metrics")
            cursor.execute(view_sql)
        except sqlite3.OperationalError:
            # json_extract is unavailable on some SQLite builds; degrade gracefully.
            pass

    # -------------------------------------------------------------------------
    # Queue management
    # -------------------------------------------------------------------------
    def enqueue_case(self, case_id: str, priority: str = "medium") -> str:
        """Insert a new review queue item and return its review_id."""
        review_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO review_queue
                    (review_id, case_id, queued_at, priority, status, last_updated)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (review_id, case_id, now, priority, "queued", now),
            )
        return review_id

    def get_queue(self, status: str = "queued", limit: int = 25) -> List[Dict[str, Any]]:
        """Fetch cases from the queue filtered by status."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM review_queue WHERE status = ? ORDER BY queued_at ASC LIMIT ?",
                (status, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_review(self, review_id: str) -> Optional[Dict[str, Any]]:
        """Return a single review entry by ID."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM review_queue WHERE review_id = ?", (review_id,)).fetchone()
        return dict(row) if row else None

    def get_cases(self, case_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        """Return review queue rows keyed by ``case_id`` for the provided identifiers."""

        normalized: List[str] = []
        seen: Set[str] = set()
        for case_id in case_ids:
            if case_id is None:
                continue
            value = str(case_id).strip()
            if not value or value in seen:
                continue
            seen.add(value)
            normalized.append(value)

        if not normalized:
            return {}

        placeholders = ",".join("?" for _ in normalized)
        query = f"SELECT * FROM review_queue WHERE case_id IN ({placeholders})"
        with self._connect() as conn:
            rows = conn.execute(query, tuple(normalized)).fetchall()
        return {str(row["case_id"]): dict(row) for row in rows}

    def update_status(self, review_id: str, status: str, notes: Optional[str] = None) -> None:
        """Update the status (accepted/rejected/etc.) and optional notes."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE review_queue
                SET status = ?, notes = ?, last_updated = ?
                WHERE review_id = ?
                """,
                (status, notes, now, review_id),
            )

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
    ) -> str:
        """Insert or replace a queue entry with explicit timestamps."""

        normalized_review_id = review_id or str(uuid.uuid4())
        queued_iso = _iso_timestamp(queued_at)
        last_iso = _iso_timestamp(last_updated) if last_updated else queued_iso
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO review_queue (review_id, case_id, queued_at, priority, status, assigned_to, notes, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(review_id) DO UPDATE SET
                    case_id=excluded.case_id,
                    queued_at=excluded.queued_at,
                    priority=excluded.priority,
                    status=excluded.status,
                    assigned_to=excluded.assigned_to,
                    notes=excluded.notes,
                    last_updated=excluded.last_updated
                """,
                (
                    normalized_review_id,
                    case_id,
                    queued_iso,
                    priority,
                    status,
                    assigned_to,
                    notes,
                    last_iso,
                ),
            )
        return normalized_review_id

    def list_dossier_candidates(self, status: str = "accepted", limit: int = 200) -> List[Dict[str, Any]]:
        """Return aggregated dossier metrics for queue entries."""

        with self._connect() as conn:
            try:
                rows = conn.execute(
                    """
                    SELECT
                        case_id,
                        status,
                        accepted_at,
                        loss_amount_usd,
                        jurisdiction,
                        victim_country,
                        offender_country,
                        cross_border,
                        loss_band,
                        geo_bucket
                    FROM dossier_candidate_metrics
                    WHERE status = ?
                    ORDER BY accepted_at DESC
                    LIMIT ?
                    """,
                    (status, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                return []
        return [dict(row) for row in rows]

    # -------------------------------------------------------------------------
    # Action logging
    # -------------------------------------------------------------------------
    def log_action(
        self,
        review_id: str,
        actor: str,
        action: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Insert a review action (for audit trail)."""
        action_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        payload_json = json.dumps(payload or {})

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO review_actions
                    (action_id, review_id, actor, action, payload, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (action_id, review_id, actor, action, payload_json, now),
            )
        return action_id

    def ensure_placeholder_review(self, review_id: str, *, case_id: str) -> None:
        """Create a queue placeholder so system logs have a review context."""

        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO review_queue (review_id, case_id, queued_at, priority, status, last_updated)
                VALUES (?, ?, ?, 'system', 'queued', ?)
                ON CONFLICT(review_id) DO NOTHING
                """,
                (review_id, case_id, now, now),
            )

    def get_actions(self, review_id: str) -> List[Dict[str, Any]]:
        """Return all actions associated with a review."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM review_actions WHERE review_id = ? ORDER BY created_at ASC",
                (review_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # -------------------------------------------------------------------------
    # Lookup helpers
    # -------------------------------------------------------------------------
    def get_reviews_by_case(self, case_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Return queue entries for a specific case_id ordered by recency."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM review_queue
                WHERE case_id = ?
                ORDER BY queued_at DESC
                LIMIT ?
                """,
                (case_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_recent_actions(self, action: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        """Return most recent actions, optionally filtered by action name."""
        with self._connect() as conn:
            if action:
                rows = conn.execute(
                    """
                    SELECT * FROM review_actions
                    WHERE action = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (action, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM review_actions
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()

        result: List[Dict[str, Any]] = []
        for r in rows:
            payload = r.get("payload") if isinstance(r, dict) else r["payload"]
            try:
                payload = json.loads(payload) if payload else {}
            except Exception:
                payload = {}
            item = dict(r)
            item["payload"] = payload
            result.append(item)
        return result

    # -------------------------------------------------------------------------
    # Saved searches
    # -------------------------------------------------------------------------
    def upsert_saved_search(
        self,
        name: str,
        params: Dict[str, Any],
        owner: Optional[str] = None,
        search_id: Optional[str] = None,
        favorite: bool = False,
        tags: Optional[List[str]] = None,
    ) -> str:
        if search_id:
            params["search_id"] = search_id
        search_id = search_id or params.get("search_id") or f"saved:{uuid.uuid4()}"
        now = datetime.now(timezone.utc).isoformat()
        payload = json.dumps(params)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO saved_searches (search_id, name, owner, params, created_at, favorite, tags)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(search_id) DO UPDATE SET
                    name = excluded.name,
                    owner = excluded.owner,
                    params = excluded.params,
                    favorite = excluded.favorite,
                    tags = excluded.tags
                """,
                (
                    search_id,
                    name,
                    owner,
                    payload,
                    now,
                    1 if favorite else 0,
                    json.dumps(tags or []),
                ),
            )
            # Enforce unique name per owner/shared scope
            dup = conn.execute(
                """
                SELECT search_id, owner FROM saved_searches
                WHERE (owner = ? OR (owner IS NULL AND ? IS NULL))
                  AND LOWER(name) = LOWER(?)
                  AND search_id != ?
                LIMIT 1
                """,
                (owner, owner, name, search_id),
            ).fetchone()
            if dup:
                dup_owner = dup[1] if isinstance(dup, tuple) else dup["owner"]
                raise ValueError(f"duplicate_saved_search:{dup_owner or ''}")
        return search_id

    def clone_saved_search(self, search_id: str, target_owner: Optional[str]) -> str:
        record = self.get_saved_search(search_id)
        if not record:
            raise ValueError("saved_search_not_found")
        new_id = f"saved:{uuid.uuid4()}"
        record["params"]["search_id"] = new_id
        return self.upsert_saved_search(
            name=record["name"],
            params=record["params"],
            owner=target_owner,
            search_id=new_id,
            favorite=record.get("favorite", False),
            tags=record.get("tags") or [],
        )

    def list_saved_searches(self, owner: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            if owner:
                rows = conn.execute(
                    """
                    SELECT * FROM saved_searches
                    WHERE owner = ? OR owner IS NULL
                    ORDER BY favorite DESC, created_at DESC
                    LIMIT ?
                    """,
                    (owner, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM saved_searches
                    ORDER BY favorite DESC, created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()

        results: List[Dict[str, Any]] = []
        for r in rows:
            params = r.get("params") if isinstance(r, dict) else r["params"]
            try:
                params = json.loads(params) if params else {}
            except Exception:
                params = {}
            item = dict(r)
            fav_val = item.get("favorite")
            if fav_val is not None:
                item["favorite"] = bool(fav_val)
            tags_val = item.get("tags")
            if isinstance(tags_val, str):
                try:
                    item["tags"] = json.loads(tags_val)
                except Exception:
                    item["tags"] = []
            item["params"] = params
            results.append(item)
        return results

    def delete_saved_search(self, search_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM saved_searches WHERE search_id = ?", (search_id,))
            return cur.rowcount > 0

    def update_saved_search(
        self,
        search_id: str,
        name: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        favorite: Optional[bool] = None,
        tags: Optional[List[str]] = None,
    ) -> bool:
        fields = []
        values: List[Any] = []
        if name is not None:
            fields.append("name = ?")
            values.append(name)
        if params is not None:
            fields.append("params = ?")
            values.append(json.dumps(params))
        if favorite is not None:
            fields.append("favorite = ?")
            values.append(1 if favorite else 0)
        if tags is not None:
            fields.append("tags = ?")
            values.append(json.dumps(tags))
        if not fields:
            return False
        with self._connect() as conn:
            if name is not None:
                owner_row = conn.execute(
                    "SELECT owner FROM saved_searches WHERE search_id = ?",
                    (search_id,),
                ).fetchone()
                if not owner_row:
                    return False
                owner = owner_row[0]
                dup = conn.execute(
                    """
                    SELECT search_id, owner FROM saved_searches
                    WHERE (owner = ? OR (owner IS NULL AND ? IS NULL))
                      AND LOWER(name) = LOWER(?)
                      AND search_id != ?
                    LIMIT 1
                    """,
                    (owner, owner, name, search_id),
                ).fetchone()
                if dup:
                    dup_owner = dup[1] if isinstance(dup, tuple) else dup["owner"]
                    raise ValueError(f"duplicate_saved_search:{dup_owner or ''}")
            values.append(search_id)
            cur = conn.execute(
                f"UPDATE saved_searches SET {', '.join(fields)} WHERE search_id = ?",
                tuple(values),
            )
            return cur.rowcount > 0

    def get_saved_search(self, search_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM saved_searches WHERE search_id = ?", (search_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        params = data.get("params")
        try:
            params = json.loads(params) if params else {}
        except Exception:
            params = {}
        data["params"] = params
        fav_val = data.get("favorite")
        if fav_val is not None:
            data["favorite"] = bool(fav_val)
        tags_val = data.get("tags")
        if isinstance(tags_val, str):
            try:
                data["tags"] = json.loads(tags_val)
            except Exception:
                data["tags"] = []
        return data

    def import_saved_search(self, payload: Dict[str, Any], owner: Optional[str] = None) -> str:
        params = payload.get("params", {}) or {}
        name = payload.get("name")
        if not name:
            raise ValueError("invalid_saved_search")
        favorite = bool(payload.get("favorite", False))
        tags = payload.get("tags") or []
        search_id = payload.get("search_id")
        # Make sure params has no lingering search_id before upserting
        params.pop("search_id", None)
        return self.upsert_saved_search(
            name=name,
            params=params,
            owner=owner,
            search_id=search_id,
            favorite=favorite,
            tags=tags,
        )

    def list_tag_presets(self, owner: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT search_id, owner, tags
                FROM saved_searches
                WHERE tags IS NOT NULL AND tags != '[]'
                  AND (? IS NULL OR owner = ?)
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (owner, owner, limit),
            ).fetchall()
        presets = []
        for row in rows:
            tags = row["tags"] if isinstance(row, dict) else row[2]
            try:
                tag_list = json.loads(tags) if tags else []
            except Exception:
                tag_list = []
            presets.append(
                {
                    "search_id": row["search_id"] if isinstance(row, dict) else row[0],
                    "owner": row["owner"] if isinstance(row, dict) else row[1],
                    "tags": tag_list,
                }
            )
        return presets

    def bulk_update_tags(
        self,
        search_ids: Iterable[str],
        add: Optional[List[str]] = None,
        remove: Optional[List[str]] = None,
        replace: Optional[List[str]] = None,
    ) -> int:
        add = [t.strip() for t in (add or []) if t.strip()]
        remove = {t.strip().lower() for t in (remove or []) if t.strip()}
        replace = [t.strip() for t in (replace or []) if t.strip()] if replace is not None else None
        updated = 0
        for search_id in search_ids:
            record = self.get_saved_search(search_id)
            if not record:
                continue
            tags = replace if replace is not None else list(record.get("tags") or [])
            if replace is None:
                tags = [t for t in tags if t.lower() not in remove]
                tags.extend(add)
            # dedupe while preserving order
            seen = set()
            normalized = []
            for tag in tags:
                key = tag.lower()
                if key not in seen:
                    seen.add(key)
                    normalized.append(tag)
            if self.update_saved_search(search_id, tags=normalized):
                updated += 1
        return updated


def _iso_timestamp(value: Optional[datetime]) -> str:
    """Return an ISO-8601 string, defaulting to UTC now when value is None."""

    dt = value or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


class SqlAlchemyReviewStore:
    """SQLAlchemy-backed review queue and audit logger."""

    def __init__(self, session_factory: sessionmaker | None = None) -> None:
        self._session_factory = session_factory or default_session_factory()

    def enqueue_case(self, case_id: str, priority: str = "medium") -> str:
        review_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        with self._session_factory() as session:
            stmt = sa.insert(sql_schema.review_queue).values(
                review_id=review_id,
                case_id=case_id,
                queued_at=now,
                priority=priority,
                status="queued",
                last_updated=now,
            )
            session.execute(stmt)
            session.commit()
        return review_id

    def get_queue(self, status: str = "queued", limit: int = 25) -> List[Dict[str, Any]]:
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
    ) -> str:
        normalized_review_id = review_id or str(uuid.uuid4())
        last_updated = last_updated or queued_at

        with self._session_factory() as session:
            stmt = sa.dialects.postgresql.insert(sql_schema.review_queue).values(
                review_id=normalized_review_id,
                case_id=case_id,
                queued_at=queued_at,
                priority=priority,
                status=status,
                assigned_to=assigned_to,
                notes=notes,
                last_updated=last_updated,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["review_id"],
                set_={
                    "case_id": stmt.excluded.case_id,
                    "queued_at": stmt.excluded.queued_at,
                    "priority": stmt.excluded.priority,
                    "status": stmt.excluded.status,
                    "assigned_to": stmt.excluded.assigned_to,
                    "notes": stmt.excluded.notes,
                    "last_updated": stmt.excluded.last_updated,
                },
            )
            session.execute(stmt)
            session.commit()
        return normalized_review_id

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
                            priority="low",
                            status="completed",
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
