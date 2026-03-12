"""Read-only store for pre-computed analytics tables.

Provides query accessors for ``entity_stats``, ``indicator_stats``,
``campaign_stats``, and ``platform_kpis`` that are populated by the
analytics aggregation job.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from i4g.store import sql as sql_schema
from i4g.store.sql import session_factory as default_session_factory

LOGGER = logging.getLogger(__name__)


class AnalyticsStore:
    """Read accessors for the pre-computed analytics tables."""

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
            sql_schema.METADATA.create_all(engine, checkfirst=True)
            self._session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        else:
            self._session_factory = default_session_factory()

    @contextmanager
    def _session_scope(self) -> Iterator[Session]:
        """Yield a session and close it on exit."""
        session = self._session_factory()
        try:
            yield session
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Entity Stats
    # ------------------------------------------------------------------

    def list_entity_stats(
        self,
        *,
        entity_type: str | None = None,
        status: str | None = None,
        min_case_count: int | None = None,
        min_loss: float | None = None,
        limit: int = 100,
        offset: int = 0,
        order_by: str = "case_count",
        descending: bool = True,
    ) -> list[dict[str, Any]]:
        """List entity stats with optional filters.

        Args:
            entity_type: Filter by entity type.
            status: Filter by status (active/dormant/flagged).
            min_case_count: Minimum case count threshold.
            min_loss: Minimum loss sum threshold.
            limit: Max rows to return.
            offset: Pagination offset.
            order_by: Column to sort by.
            descending: Sort direction.

        Returns:
            List of entity_stats dicts.
        """
        es = sql_schema.entity_stats
        stmt = sa.select(es)

        if entity_type:
            stmt = stmt.where(es.c.entity_type == entity_type)
        if status:
            stmt = stmt.where(es.c.status == status)
        if min_case_count is not None:
            stmt = stmt.where(es.c.case_count >= min_case_count)
        if min_loss is not None:
            stmt = stmt.where(es.c.loss_sum >= min_loss)

        sort_col = getattr(es.c, order_by, es.c.case_count)
        stmt = stmt.order_by(sort_col.desc() if descending else sort_col.asc())
        stmt = stmt.limit(limit).offset(offset)

        with self._session_scope() as session:
            rows = session.execute(stmt).all()
            return [dict(r._mapping) for r in rows]

    def get_entity_stat(self, entity_type: str, canonical_value: str) -> dict[str, Any] | None:
        """Fetch stats for a specific entity.

        Args:
            entity_type: The entity type.
            canonical_value: The normalized entity value.

        Returns:
            Entity stats dict or None.
        """
        es = sql_schema.entity_stats
        with self._session_scope() as session:
            row = session.execute(
                sa.select(es).where(sa.and_(es.c.entity_type == entity_type, es.c.canonical_value == canonical_value))
            ).first()
            if not row:
                return None
            return dict(row._mapping)

    # ------------------------------------------------------------------
    # Indicator Stats
    # ------------------------------------------------------------------

    def list_indicator_stats(
        self,
        *,
        category: str | None = None,
        min_case_count: int | None = None,
        limit: int = 100,
        offset: int = 0,
        order_by: str = "case_count",
        descending: bool = True,
    ) -> list[dict[str, Any]]:
        """List indicator stats with optional filters.

        Args:
            category: Filter by indicator category (bank/crypto/payments).
            min_case_count: Minimum case count threshold.
            limit: Max rows.
            offset: Pagination offset.
            order_by: Sort column.
            descending: Sort direction.

        Returns:
            List of indicator_stats dicts.
        """
        ist = sql_schema.indicator_stats
        stmt = sa.select(ist)

        if category:
            stmt = stmt.where(ist.c.category == category)
        if min_case_count is not None:
            stmt = stmt.where(ist.c.case_count >= min_case_count)

        sort_col = getattr(ist.c, order_by, ist.c.case_count)
        stmt = stmt.order_by(sort_col.desc() if descending else sort_col.asc())
        stmt = stmt.limit(limit).offset(offset)

        with self._session_scope() as session:
            rows = session.execute(stmt).all()
            return [dict(r._mapping) for r in rows]

    def get_indicator_stat(self, indicator_id: str) -> dict[str, Any] | None:
        """Fetch stats for a specific indicator.

        Args:
            indicator_id: The indicator UUID.

        Returns:
            Indicator stats dict or None.
        """
        ist = sql_schema.indicator_stats
        with self._session_scope() as session:
            row = session.execute(sa.select(ist).where(ist.c.indicator_id == indicator_id)).first()
            if not row:
                return None
            return dict(row._mapping)

    # ------------------------------------------------------------------
    # Campaign Stats
    # ------------------------------------------------------------------

    def list_campaign_stats(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List campaign stats with optional status filter.

        Args:
            status: Filter by campaign status.
            limit: Max rows.
            offset: Pagination offset.

        Returns:
            List of campaign_stats dicts.
        """
        cs = sql_schema.campaign_stats
        stmt = sa.select(cs).order_by(cs.c.risk_score.desc())

        if status:
            stmt = stmt.where(cs.c.status == status)
        stmt = stmt.limit(limit).offset(offset)

        with self._session_scope() as session:
            rows = session.execute(stmt).all()
            return [dict(r._mapping) for r in rows]

    def get_campaign_stat(self, campaign_id: str) -> dict[str, Any] | None:
        """Fetch stats for a specific campaign.

        Args:
            campaign_id: The campaign UUID.

        Returns:
            Campaign stats dict or None.
        """
        cs = sql_schema.campaign_stats
        with self._session_scope() as session:
            row = session.execute(sa.select(cs).where(cs.c.campaign_id == campaign_id)).first()
            if not row:
                return None
            return dict(row._mapping)

    # ------------------------------------------------------------------
    # Platform KPIs
    # ------------------------------------------------------------------

    def list_platform_kpis(
        self,
        *,
        period_type: str = "daily",
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 365,
    ) -> list[dict[str, Any]]:
        """Query platform KPIs for a date range.

        Args:
            period_type: "day", "week", "month", or "quarter".
            start_date: Start of the date range (inclusive).
            end_date: End of the date range (inclusive).
            limit: Max rows.

        Returns:
            List of platform_kpis dicts ordered by period_start ascending.
        """
        pk = sql_schema.platform_kpis
        stmt = sa.select(pk).where(pk.c.period_type == period_type)

        if start_date:
            stmt = stmt.where(pk.c.period_start >= start_date)
        if end_date:
            stmt = stmt.where(pk.c.period_start <= end_date)

        stmt = stmt.order_by(pk.c.period_start.asc()).limit(limit)

        with self._session_scope() as session:
            rows = session.execute(stmt).all()
            return [dict(r._mapping) for r in rows]

    def get_latest_kpi(self, period_type: str = "daily") -> dict[str, Any] | None:
        """Fetch the most recent KPI row for a given period type.

        Args:
            period_type: The period granularity.

        Returns:
            The latest KPI dict or None.
        """
        pk = sql_schema.platform_kpis
        with self._session_scope() as session:
            row = session.execute(
                sa.select(pk).where(pk.c.period_type == period_type).order_by(pk.c.period_start.desc()).limit(1)
            ).first()
            if not row:
                return None
            return dict(row._mapping)
