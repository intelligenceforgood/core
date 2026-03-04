"""SSI event persistence store — Phase 3B cloud live-monitoring.

``SsiEventsStore`` writes investigation events into the ``ssi_events`` table
so they can be streamed to the UI via SSE and replayed on the investigation
detail page.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from i4g.store import sql as sql_schema
from i4g.store.sql import METADATA
from i4g.store.sql import session_factory as default_session_factory

logger = logging.getLogger(__name__)


class SsiEventsStore:
    """Persist and retrieve SSI investigation events.

    Supports both SQLite (local dev) and Cloud SQL (production) via an
    injected ``session_factory``.

    Args:
        db_path: Path to a local SQLite file.  Mutually exclusive with
            *session_factory*.
        session_factory: Pre-configured ``sessionmaker`` (e.g. Cloud SQL
            or a shared test fixture).
    """

    def __init__(
        self,
        db_path: str | None = None,
        *,
        session_factory: sessionmaker | None = None,
    ) -> None:
        if session_factory is not None:
            self._session_factory = session_factory
        elif db_path is not None:
            engine = sa.create_engine(
                f"sqlite:///{db_path}",
                pool_pre_ping=True,
                connect_args={"check_same_thread": False},
            )
            METADATA.create_all(engine, checkfirst=True)
            self._session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        else:
            self._session_factory = default_session_factory()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def insert_event(
        self,
        *,
        scan_id: str,
        event_type: str,
        timestamp: datetime | str | None = None,
        data_json: dict[str, Any] | None = None,
        screenshot_url: str | None = None,
        event_id: str | None = None,
    ) -> str:
        """Insert a single event row into ``ssi_events``.

        Args:
            scan_id: The SSI investigation scan ID.
            event_type: The event type string (e.g. ``"screenshot_update"``).
            timestamp: Event timestamp; defaults to now (UTC) if not provided.
            data_json: Arbitrary event payload including inline base64 screenshots.
            screenshot_url: Optional GCS URL for future use (nullable).
            event_id: Optional pre-assigned UUID string.  Generates one if absent.

        Returns:
            The ``id`` of the inserted row.
        """
        event_id = event_id or str(uuid4())
        if timestamp is None:
            ts = datetime.now(UTC)
        elif isinstance(timestamp, str):
            ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        else:
            ts = timestamp

        now = datetime.now(UTC)
        with self._session_factory() as session:
            session.execute(
                sa.insert(sql_schema.ssi_events).values(
                    id=event_id,
                    scan_id=scan_id,
                    event_type=event_type,
                    timestamp=ts,
                    data_json=data_json or {},
                    screenshot_url=screenshot_url,
                    created_at=now,
                )
            )
            session.commit()
        return event_id

    def insert_event_batch(self, events: list[dict[str, Any]]) -> list[str]:
        """Insert a batch of events in a single transaction.

        Args:
            events: List of event dicts.  Each must contain at least
                ``scan_id``, ``event_type``, and ``timestamp``.

        Returns:
            List of inserted row IDs (one per event).
        """
        if not events:
            return []

        rows: list[dict[str, Any]] = []
        ids: list[str] = []
        now = datetime.now(UTC)

        for ev in events:
            event_id = ev.get("id") or str(uuid4())
            ids.append(event_id)
            raw_ts = ev.get("timestamp")
            if raw_ts is None:
                ts = now
            elif isinstance(raw_ts, str):
                ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
            else:
                ts = raw_ts

            rows.append(
                {
                    "id": event_id,
                    "scan_id": ev["scan_id"],
                    "event_type": ev["event_type"],
                    "timestamp": ts,
                    "data_json": ev.get("data_json") or ev.get("data") or {},
                    "screenshot_url": ev.get("screenshot_url"),
                    "created_at": now,
                }
            )

        with self._session_factory() as session:
            session.execute(sa.insert(sql_schema.ssi_events), rows)
            session.commit()

        logger.debug("Inserted %d ssi_events for scan %s", len(rows), events[0].get("scan_id", "?"))
        return ids

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_events(
        self,
        scan_id: str,
        *,
        after_timestamp: datetime | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Return events for a scan, ordered by timestamp ascending.

        Args:
            scan_id: The scan to query.
            after_timestamp: When provided, return only events after this
                timestamp (exclusive).  Used for incremental SSE polling.
            limit: Maximum rows to return.

        Returns:
            List of event dicts with keys: ``id``, ``scan_id``, ``event_type``,
            ``timestamp`` (ISO-8601 string), ``data_json``, ``screenshot_url``.
        """
        tbl = sql_schema.ssi_events
        stmt = sa.select(tbl).where(tbl.c.scan_id == scan_id).order_by(tbl.c.timestamp.asc()).limit(limit)
        if after_timestamp is not None:
            stmt = stmt.where(tbl.c.timestamp > after_timestamp)

        with self._session_factory() as session:
            rows = session.execute(stmt).mappings().all()

        return [_serialize_event(dict(row)) for row in rows]

    def get_latest_timestamp(self, scan_id: str) -> datetime | None:
        """Return the timestamp of the most recent event for a scan.

        Args:
            scan_id: The scan to query.

        Returns:
            Latest event timestamp or ``None`` if no events exist yet.
        """
        tbl = sql_schema.ssi_events
        stmt = sa.select(sa.func.max(tbl.c.timestamp)).where(tbl.c.scan_id == scan_id)
        with self._session_factory() as session:
            result = session.execute(stmt).scalar()
        return result

    # ------------------------------------------------------------------
    # Guidance commands (Phase 3C)
    # ------------------------------------------------------------------

    def insert_guidance_command(
        self,
        *,
        scan_id: str,
        action: str,
        value: str = "",
        reason: str = "",
        command_id: str | None = None,
    ) -> str:
        """Insert a guidance command submitted by an analyst.

        Args:
            scan_id: The SSI investigation scan ID.
            action: Guidance action (click, type, goto, skip, continue).
            value: Action-specific value (CSS selector, URL, text, etc.).
            reason: Optional human-readable reason.
            command_id: Optional pre-assigned UUID.  Generates one if absent.

        Returns:
            The ``id`` of the inserted command row.
        """
        command_id = command_id or str(uuid4())
        now = datetime.now(UTC)
        tbl = sql_schema.ssi_guidance_commands
        with self._session_factory() as session:
            session.execute(
                sa.insert(tbl).values(
                    id=command_id,
                    scan_id=scan_id,
                    action=action,
                    value=value,
                    reason=reason,
                    acknowledged=False,
                    created_at=now,
                )
            )
            session.commit()
        return command_id

    def get_pending_guidance(self, scan_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """Return unacknowledged guidance commands for a scan.

        Args:
            scan_id: The scan to query.
            limit: Maximum commands to return.

        Returns:
            List of command dicts ordered by creation time ascending.
        """
        tbl = sql_schema.ssi_guidance_commands
        stmt = (
            sa.select(tbl)
            .where(tbl.c.scan_id == scan_id)
            .where(tbl.c.acknowledged == False)  # noqa: E712
            .order_by(tbl.c.created_at.asc())
            .limit(limit)
        )
        with self._session_factory() as session:
            rows = session.execute(stmt).mappings().all()
        return [_serialize_guidance(dict(row)) for row in rows]

    def acknowledge_guidance(self, command_id: str) -> bool:
        """Mark a guidance command as acknowledged by SSI.

        Args:
            command_id: The command row ID.

        Returns:
            ``True`` if the row was updated, ``False`` if not found.
        """
        tbl = sql_schema.ssi_guidance_commands
        now = datetime.now(UTC)
        with self._session_factory() as session:
            result = session.execute(
                sa.update(tbl).where(tbl.c.id == command_id).values(acknowledged=True, acknowledged_at=now)
            )
            session.commit()
        return result.rowcount > 0


def _serialize_event(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a raw DB row to a JSON-safe dict.

    Args:
        row: Raw row dict from SQLAlchemy mappings.

    Returns:
        Dict with datetime values replaced by ISO-8601 strings.
    """
    for key in ("timestamp", "created_at"):
        val = row.get(key)
        if isinstance(val, datetime):
            row[key] = val.isoformat()
    return row


def _serialize_guidance(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a guidance command DB row to a JSON-safe dict.

    Args:
        row: Raw row dict from SQLAlchemy mappings.

    Returns:
        Dict with datetime values replaced by ISO-8601 strings.
    """
    for key in ("created_at", "acknowledged_at"):
        val = row.get(key)
        if isinstance(val, datetime):
            row[key] = val.isoformat()
    return row
