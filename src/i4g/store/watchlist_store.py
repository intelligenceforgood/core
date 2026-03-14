"""Watchlist store for pinned entity monitoring and alert management.

Provides CRUD for ``watchlist_items`` and ``watchlist_alerts`` tables,
supporting entity pinning, alert condition configuration, and alert
lifecycle management (F-43).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from i4g.store.sql import METADATA, build_engine, watchlist_alerts, watchlist_items


class WatchlistStore:
    """Store for managing watchlist items and associated alerts.

    Args:
        db_path: Path to SQLite database (local mode).
        session_factory: SQLAlchemy session factory (Cloud SQL mode).
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        session_factory: sessionmaker | None = None,
    ) -> None:
        if session_factory is not None:
            self._session_factory = session_factory
        elif db_path is not None:
            url = f"sqlite:///{Path(db_path).as_posix()}"
            engine = sa.create_engine(url, future=True, connect_args={"check_same_thread": False})
            METADATA.create_all(engine, checkfirst=True)
            self._session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        else:
            engine = build_engine()
            METADATA.create_all(engine, checkfirst=True)
            self._session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    @contextmanager
    def _session_scope(self) -> Iterator[Session]:
        """Yield a session and auto-close on exit."""
        session: Session = self._session_factory()
        try:
            yield session
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Watchlist CRUD
    # ------------------------------------------------------------------

    def add_item(
        self,
        *,
        entity_type: str,
        canonical_value: str,
        alert_on_new_case: bool = True,
        alert_on_loss_increase: bool = False,
        loss_threshold: float | None = None,
        note: str | None = None,
        created_by: str = "system",
    ) -> str | None:
        """Pin an entity to the watchlist.

        Args:
            entity_type: Entity type (e.g. ``crypto_wallet``).
            canonical_value: Entity canonical value.
            alert_on_new_case: Alert when new cases reference this entity.
            alert_on_loss_increase: Alert when cumulative loss exceeds threshold.
            loss_threshold: Loss value that triggers a loss-increase alert.
            note: Optional analyst note.
            created_by: User who pinned the entity.

        Returns:
            The new watchlist item ID, or ``None`` if the entity is already watched.
        """
        watchlist_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        try:
            with self._session_scope() as session:
                session.execute(
                    sa.insert(watchlist_items).values(
                        watchlist_id=watchlist_id,
                        entity_type=entity_type,
                        canonical_value=canonical_value,
                        alert_on_new_case=alert_on_new_case,
                        alert_on_loss_increase=alert_on_loss_increase,
                        loss_threshold=loss_threshold,
                        note=note,
                        created_by=created_by,
                        created_at=now,
                        updated_at=now,
                    )
                )
                session.commit()
        except sa.exc.IntegrityError:
            return None
        return watchlist_id

    def remove_item(self, watchlist_id: str) -> bool:
        """Remove an entity from the watchlist.

        Args:
            watchlist_id: ID of the watchlist entry.

        Returns:
            True if the item was deleted.
        """
        with self._session_scope() as session:
            # Also remove associated alerts
            session.execute(sa.delete(watchlist_alerts).where(watchlist_alerts.c.watchlist_id == watchlist_id))
            result = session.execute(sa.delete(watchlist_items).where(watchlist_items.c.watchlist_id == watchlist_id))
            session.commit()
            return result.rowcount > 0

    def get_item(self, watchlist_id: str) -> dict[str, Any] | None:
        """Retrieve a single watchlist item by ID.

        Args:
            watchlist_id: Watchlist entry ID.

        Returns:
            Watchlist item dict or ``None``.
        """
        with self._session_scope() as session:
            row = session.execute(
                sa.select(watchlist_items).where(watchlist_items.c.watchlist_id == watchlist_id)
            ).first()
            return dict(row._mapping) if row else None

    def list_items(
        self,
        *,
        created_by: str | None = None,
        entity_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List watchlist items with optional filters.

        Args:
            created_by: Filter by creator.
            entity_type: Filter by entity type.
            limit: Page size.
            offset: Pagination offset.

        Returns:
            List of watchlist item dicts.
        """
        stmt = sa.select(watchlist_items).order_by(watchlist_items.c.created_at.desc())
        if created_by:
            stmt = stmt.where(watchlist_items.c.created_by == created_by)
        if entity_type:
            stmt = stmt.where(watchlist_items.c.entity_type == entity_type)
        stmt = stmt.limit(limit).offset(offset)
        with self._session_scope() as session:
            rows = session.execute(stmt).fetchall()
            return [dict(r._mapping) for r in rows]

    def count_items(self, *, created_by: str | None = None) -> int:
        """Count watchlist items.

        Args:
            created_by: Optional filter by creator.

        Returns:
            Total number of matching items.
        """
        stmt = sa.select(sa.func.count()).select_from(watchlist_items)
        if created_by:
            stmt = stmt.where(watchlist_items.c.created_by == created_by)
        with self._session_scope() as session:
            return session.execute(stmt).scalar() or 0

    def update_item(
        self,
        watchlist_id: str,
        *,
        alert_on_new_case: bool | None = None,
        alert_on_loss_increase: bool | None = None,
        loss_threshold: float | None = None,
        note: str | None = None,
    ) -> bool:
        """Update alert conditions for a watchlist item.

        Args:
            watchlist_id: Item ID.
            alert_on_new_case: Toggle new-case alerts.
            alert_on_loss_increase: Toggle loss-increase alerts.
            loss_threshold: Update loss threshold.
            note: Update analyst note.

        Returns:
            True if the item was updated.
        """
        values: dict[str, Any] = {"updated_at": datetime.now(UTC)}
        if alert_on_new_case is not None:
            values["alert_on_new_case"] = alert_on_new_case
        if alert_on_loss_increase is not None:
            values["alert_on_loss_increase"] = alert_on_loss_increase
        if loss_threshold is not None:
            values["loss_threshold"] = loss_threshold
        if note is not None:
            values["note"] = note

        with self._session_scope() as session:
            result = session.execute(
                sa.update(watchlist_items).where(watchlist_items.c.watchlist_id == watchlist_id).values(**values)
            )
            session.commit()
            return result.rowcount > 0

    def find_by_entity(self, entity_type: str, canonical_value: str) -> dict[str, Any] | None:
        """Look up a watchlist item by entity identity.

        Args:
            entity_type: Entity type.
            canonical_value: Entity canonical value.

        Returns:
            Watchlist item dict or ``None``.
        """
        with self._session_scope() as session:
            row = session.execute(
                sa.select(watchlist_items).where(
                    watchlist_items.c.entity_type == entity_type,
                    watchlist_items.c.canonical_value == canonical_value,
                )
            ).first()
            return dict(row._mapping) if row else None

    # ------------------------------------------------------------------
    # Alerts
    # ------------------------------------------------------------------

    def create_alert(
        self,
        *,
        watchlist_id: str,
        alert_type: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> str:
        """Create an alert for a watchlist item.

        Args:
            watchlist_id: Watchlist item ID this alert belongs to.
            alert_type: Alert category (``new_case`` or ``loss_increase``).
            message: Human-readable alert message.
            data: Optional structured alert data.

        Returns:
            The new alert ID.
        """
        alert_id = str(uuid.uuid4())
        with self._session_scope() as session:
            session.execute(
                sa.insert(watchlist_alerts).values(
                    alert_id=alert_id,
                    watchlist_id=watchlist_id,
                    alert_type=alert_type,
                    message=message,
                    is_read=False,
                    data=data,
                    created_at=datetime.now(UTC),
                )
            )
            session.commit()
        return alert_id

    def list_alerts(
        self,
        *,
        watchlist_id: str | None = None,
        unread_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List alerts, optionally filtered by watchlist item or read status.

        Args:
            watchlist_id: Filter alerts for a specific watchlist entry.
            unread_only: Only return unread alerts.
            limit: Page size.
            offset: Pagination offset.

        Returns:
            List of alert dicts.
        """
        stmt = sa.select(watchlist_alerts).order_by(watchlist_alerts.c.created_at.desc())
        if watchlist_id:
            stmt = stmt.where(watchlist_alerts.c.watchlist_id == watchlist_id)
        if unread_only:
            stmt = stmt.where(watchlist_alerts.c.is_read == False)  # noqa: E712
        stmt = stmt.limit(limit).offset(offset)
        with self._session_scope() as session:
            rows = session.execute(stmt).fetchall()
            return [dict(r._mapping) for r in rows]

    def mark_alert_read(self, alert_id: str) -> bool:
        """Mark an alert as read.

        Args:
            alert_id: Alert ID.

        Returns:
            True if updated.
        """
        with self._session_scope() as session:
            result = session.execute(
                sa.update(watchlist_alerts).where(watchlist_alerts.c.alert_id == alert_id).values(is_read=True)
            )
            session.commit()
            return result.rowcount > 0

    def mark_all_read(self, *, watchlist_id: str | None = None) -> int:
        """Mark all alerts as read.

        Args:
            watchlist_id: Optionally scope to a specific watchlist item.

        Returns:
            Number of alerts marked.
        """
        stmt = sa.update(watchlist_alerts).where(watchlist_alerts.c.is_read == False).values(is_read=True)  # noqa: E712
        if watchlist_id:
            stmt = stmt.where(watchlist_alerts.c.watchlist_id == watchlist_id)
        with self._session_scope() as session:
            result = session.execute(stmt)
            session.commit()
            return result.rowcount

    def count_unread_alerts(self, *, watchlist_id: str | None = None) -> int:
        """Count unread alerts.

        Args:
            watchlist_id: Optionally scope to a specific watchlist item.

        Returns:
            Number of unread alerts.
        """
        stmt = (
            sa.select(sa.func.count())
            .select_from(watchlist_alerts)
            .where(watchlist_alerts.c.is_read == False)  # noqa: E712
        )
        if watchlist_id:
            stmt = stmt.where(watchlist_alerts.c.watchlist_id == watchlist_id)
        with self._session_scope() as session:
            return session.execute(stmt).scalar() or 0
