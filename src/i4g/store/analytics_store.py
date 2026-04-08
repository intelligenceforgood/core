"""Read-only store for pre-computed analytics tables.

Provides query accessors for ``entity_stats``, ``indicator_stats``,
``campaign_stats``, and ``platform_kpis`` that are populated by the
analytics aggregation job.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from i4g.store import sql as sql_schema
from i4g.store.sql import dialect_group_concat
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

    def list_entity_types(self) -> list[str]:
        """Return distinct entity types from entity_stats, sorted alphabetically."""
        es = sql_schema.entity_stats
        with self._session_scope() as session:
            rows = session.execute(sa.select(sa.distinct(es.c.entity_type)).order_by(es.c.entity_type)).all()
            return [r[0] for r in rows]

    @staticmethod
    def _entity_filters(
        *,
        entity_type: str | None = None,
        entity_types: frozenset[str] | None = None,
        status: str | None = None,
        min_case_count: int | None = None,
        min_loss: float | None = None,
    ) -> list[sa.ColumnElement]:
        """Return WHERE clauses for entity_stats queries."""
        es = sql_schema.entity_stats
        clauses: list[sa.ColumnElement] = []
        if entity_type:
            clauses.append(es.c.entity_type == entity_type)
        if entity_types:
            clauses.append(es.c.entity_type.in_(entity_types))
        if status:
            clauses.append(es.c.status == status)
        if min_case_count is not None:
            clauses.append(es.c.case_count >= min_case_count)
        if min_loss is not None:
            clauses.append(es.c.loss_sum >= min_loss)
        return clauses

    def count_entity_stats(
        self,
        *,
        entity_type: str | None = None,
        entity_types: frozenset[str] | None = None,
        status: str | None = None,
        min_case_count: int | None = None,
        min_loss: float | None = None,
    ) -> int:
        """Return total count of entity_stats matching the given filters."""
        es = sql_schema.entity_stats
        stmt = sa.select(sa.func.count()).select_from(es)
        for clause in self._entity_filters(
            entity_type=entity_type,
            entity_types=entity_types,
            status=status,
            min_case_count=min_case_count,
            min_loss=min_loss,
        ):
            stmt = stmt.where(clause)
        with self._session_scope() as session:
            return session.execute(stmt).scalar() or 0

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
        for clause in self._entity_filters(
            entity_type=entity_type,
            status=status,
            min_case_count=min_case_count,
            min_loss=min_loss,
        ):
            stmt = stmt.where(clause)

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
        for clause in self._indicator_filters(category=category, min_case_count=min_case_count):
            stmt = stmt.where(clause)

        sort_col = getattr(ist.c, order_by, ist.c.case_count)
        stmt = stmt.order_by(sort_col.desc() if descending else sort_col.asc())
        stmt = stmt.limit(limit).offset(offset)

        with self._session_scope() as session:
            rows = session.execute(stmt).all()
            return [dict(r._mapping) for r in rows]

    @staticmethod
    def _indicator_filters(
        *,
        category: str | None = None,
        min_case_count: int | None = None,
    ) -> list[sa.ColumnElement]:
        """Return WHERE clauses for indicator_stats queries."""
        ist = sql_schema.indicator_stats
        clauses: list[sa.ColumnElement] = []
        if category:
            clauses.append(ist.c.category == category)
        if min_case_count is not None:
            clauses.append(ist.c.case_count >= min_case_count)
        return clauses

    def count_indicator_stats(
        self,
        *,
        category: str | None = None,
        min_case_count: int | None = None,
    ) -> int:
        """Return total count of indicator_stats matching the given filters."""
        ist = sql_schema.indicator_stats
        stmt = sa.select(sa.func.count()).select_from(ist)
        for clause in self._indicator_filters(category=category, min_case_count=min_case_count):
            stmt = stmt.where(clause)
        with self._session_scope() as session:
            return session.execute(stmt).scalar() or 0

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
        engagement_id: str | None = "__global__",
        limit: int = 365,
    ) -> list[dict[str, Any]]:
        """Query platform KPIs for a date range.

        Args:
            period_type: "day", "week", "month", or "quarter".
            start_date: Start of the date range (inclusive).
            end_date: End of the date range (inclusive).
            engagement_id: Filter to a specific engagement. Defaults to
                ``"__global__"`` for aggregate rows. Pass an engagement
                UUID for per-engagement data.
            limit: Max rows.

        Returns:
            List of platform_kpis dicts ordered by period_start ascending.
        """
        pk = sql_schema.platform_kpis
        stmt = sa.select(pk).where(pk.c.period_type == period_type)

        if engagement_id is not None:
            stmt = stmt.where(pk.c.engagement_id == engagement_id)

        if start_date:
            stmt = stmt.where(pk.c.period_start >= start_date)
        if end_date:
            stmt = stmt.where(pk.c.period_start <= end_date)

        stmt = stmt.order_by(pk.c.period_start.asc()).limit(limit)

        with self._session_scope() as session:
            rows = session.execute(stmt).all()
            return [dict(r._mapping) for r in rows]

    def get_latest_kpi(
        self,
        period_type: str = "daily",
        engagement_id: str | None = "__global__",
    ) -> dict[str, Any] | None:
        """Fetch the most recent KPI row for a given period type.

        Args:
            period_type: The period granularity.
            engagement_id: Filter to a specific engagement. Defaults to
                ``"__global__"`` for aggregate rows.

        Returns:
            The latest KPI dict or None.
        """
        pk = sql_schema.platform_kpis
        stmt = sa.select(pk).where(pk.c.period_type == period_type)
        if engagement_id is not None:
            stmt = stmt.where(pk.c.engagement_id == engagement_id)
        stmt = stmt.order_by(pk.c.period_start.desc()).limit(1)
        with self._session_scope() as session:
            row = session.execute(stmt).first()
            if not row:
                return None
            return dict(row._mapping)

    # ------------------------------------------------------------------
    # Entity Activity (sparkline data)
    # ------------------------------------------------------------------

    def get_entity_activity(
        self,
        entity_type: str,
        canonical_value: str,
    ) -> list[dict[str, Any]]:
        """Return weekly case counts for an entity over its lifetime.

        Computes a weekly time-series by joining entities → cases and
        grouping by ISO week. Used for sparkline rendering.

        Args:
            entity_type: The entity type.
            canonical_value: The normalized entity value.

        Returns:
            List of dicts with ``week`` (ISO date string) and ``case_count``.
        """
        entities_t = sql_schema.entities
        cases_t = sql_schema.cases

        with self._session_scope() as session:
            # Find case IDs linked to this entity
            case_ids_q = sa.select(entities_t.c.case_id).where(
                sa.and_(
                    entities_t.c.entity_type == entity_type,
                    entities_t.c.canonical_value == canonical_value,
                )
            )
            case_id_rows = session.execute(case_ids_q).all()
            if not case_id_rows:
                return []

            case_ids = [r[0] for r in case_id_rows]

            # Group cases by week
            rows = session.execute(
                sa.select(cases_t.c.created_at)
                .where(cases_t.c.case_id.in_(case_ids))
                .order_by(cases_t.c.created_at.asc())
            ).all()

            from collections import defaultdict
            from datetime import datetime as dt

            weekly: dict[str, int] = defaultdict(int)
            for (created_at,) in rows:
                if created_at is None:
                    continue
                if isinstance(created_at, str):
                    try:
                        created_at = dt.fromisoformat(created_at)
                    except ValueError:
                        continue
                # ISO week start (Monday)
                iso_cal = created_at.isocalendar()
                week_key = f"{iso_cal[0]}-W{iso_cal[1]:02d}"
                weekly[week_key] += 1

            return [{"week": k, "case_count": v} for k, v in sorted(weekly.items())]

    # ------------------------------------------------------------------
    # Entity Neighbors (1-hop co-occurrence graph)
    # ------------------------------------------------------------------

    def get_entity_neighbors(
        self,
        entity_type: str,
        canonical_value: str,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Return entities that co-occur in the same cases as the seed entity.

        Finds shared case IDs between the seed and other entities, then
        returns the top neighbors by number of shared cases.

        Args:
            entity_type: Seed entity type.
            canonical_value: Seed entity value.
            limit: Max neighbors to return.

        Returns:
            List of neighbor dicts with entity_type, canonical_value,
            case_count, shared_cases count.
        """
        entities_t = sql_schema.entities
        es = sql_schema.entity_stats

        with self._session_scope() as session:
            # Step 1: Find case IDs for the seed entity
            seed_cases_q = sa.select(entities_t.c.case_id).where(
                sa.and_(
                    entities_t.c.entity_type == entity_type,
                    entities_t.c.canonical_value == canonical_value,
                )
            )
            seed_rows = session.execute(seed_cases_q).all()
            if not seed_rows:
                return []

            seed_case_ids = [r[0] for r in seed_rows]

            # Step 2: Find other entities in those cases
            neighbor_q = (
                sa.select(
                    entities_t.c.entity_type,
                    entities_t.c.canonical_value,
                    sa.func.count(sa.distinct(entities_t.c.case_id)).label("shared_cases"),
                    dialect_group_concat(session, entities_t.c.case_id).label("shared_case_ids"),
                )
                .where(entities_t.c.case_id.in_(seed_case_ids))
                .where(
                    sa.or_(
                        entities_t.c.entity_type != entity_type,
                        entities_t.c.canonical_value != canonical_value,
                    )
                )
                .group_by(entities_t.c.entity_type, entities_t.c.canonical_value)
                .order_by(sa.desc("shared_cases"))
                .limit(limit)
            )
            neighbor_rows = session.execute(neighbor_q).all()

            results = []
            for row in neighbor_rows:
                n_et = row[0]
                n_cv = row[1]
                n_shared = row[2]
                raw_ids = row[3] or ""
                case_id_list = [cid for cid in raw_ids.split(",") if cid][:20]
                # Look up stats for case_count
                stat = session.execute(
                    sa.select(es.c.case_count).where(sa.and_(es.c.entity_type == n_et, es.c.canonical_value == n_cv))
                ).first()
                results.append(
                    {
                        "entity_type": n_et,
                        "canonical_value": n_cv,
                        "case_count": stat[0] if stat else 0,
                        "shared_cases": n_shared,
                        "shared_case_ids": case_id_list,
                    }
                )

            return results

    def update_entity_status(self, entity_type: str, canonical_value: str, status: str) -> bool:
        """Update the status of an entity in entity_stats.

        Args:
            entity_type: Entity type.
            canonical_value: Entity canonical value.
            status: New status value.

        Returns:
            True if the entity was found and updated, False otherwise.
        """
        es = sql_schema.entity_stats
        with self._session_scope() as session:
            result = session.execute(
                sa.update(es)
                .where(sa.and_(es.c.entity_type == entity_type, es.c.canonical_value == canonical_value))
                .values(status=status, updated_at=datetime.now(UTC))
            )
            session.commit()
            return (result.rowcount or 0) > 0
