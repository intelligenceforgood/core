"""Impact analytics API router.

Provides endpoints for the Impact Dashboard: KPI cards with vs-prior-period
trends, loss-by-taxonomy treemap, detection velocity chart, pipeline funnel,
and cumulative indicator time-series.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from i4g.api.auth import require_token
from i4g.api.camel import CamelModel
from i4g.api.review_deps import get_db_session
from i4g.services.factories import build_analytics_store
from i4g.store.analytics_store import AnalyticsStore
from i4g.store.sql import (
    cases,
    entity_stats,
    indicator_stats,
    intake_records,
    review_actions,
    review_queue,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/impact",
    tags=["impact"],
    dependencies=[Depends(require_token)],
)


# ---------------------------------------------------------------------------
# Dependency helpers
# ---------------------------------------------------------------------------


def _get_analytics_store() -> AnalyticsStore:
    """Return an AnalyticsStore instance."""
    return build_analytics_store()


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class KpiCardItem(CamelModel):
    """Single KPI card with value, trend direction, and change text."""

    label: str
    value: str
    trend: str = "flat"
    change: str = "No change"


class DashboardResponse(CamelModel):
    """Impact Dashboard top-level response."""

    kpis: list[KpiCardItem] = Field(default_factory=list)
    period_label: str = ""


class TaxonomyLossItem(CamelModel):
    """One node in the loss-by-taxonomy treemap."""

    label: str
    loss_sum: float = 0.0
    case_count: int = 0


class DetectionVelocityPoint(CamelModel):
    """Single point on the detection velocity line chart."""

    period: str
    proactive: int = 0
    reactive: int = 0
    total: int = 0


class PipelineFunnelStage(CamelModel):
    """Single stage in the pipeline funnel."""

    stage: str
    count: int = 0


class CumulativeIndicatorPoint(CamelModel):
    """Single point in the cumulative indicators time-series."""

    period: str
    bank: int = 0
    crypto: int = 0
    domain: int = 0
    ip: int = 0
    other: int = 0
    total: int = 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _calculate_trend(current: float, previous: float) -> tuple[str, str]:
    """Compute trend direction and human-readable change text."""
    if previous == 0:
        if current == 0:
            return "flat", "No change"
        return "up", "New"

    diff = current - previous
    pct = (diff / previous) * 100
    direction = "up" if diff > 0 else ("down" if diff < 0 else "flat")
    return direction, f"{diff:+.0f} ({pct:+.1f}%)"


def _parse_period(period: str) -> tuple[date, date]:
    """Return (start, end) dates for preset period strings.

    Args:
        period: One of ``7d``, ``30d``, ``90d``, ``quarter``, ``year``.

    Returns:
        Tuple of (start_date, end_date).
    """
    today = date.today()
    mapping: dict[str, int] = {
        "7d": 7,
        "30d": 30,
        "90d": 90,
        "quarter": 91,
        "year": 365,
    }
    days = mapping.get(period, 30)
    return today - timedelta(days=days), today


# ---------------------------------------------------------------------------
# S3-01  /api/impact/dashboard — KPI cards with vs-prior-period trend
# ---------------------------------------------------------------------------


@router.get("/dashboard", response_model=DashboardResponse)
def get_impact_dashboard(
    period: str = Query("30d", description="Period preset: 7d, 30d, 90d, quarter, year"),
    store: AnalyticsStore = Depends(_get_analytics_store),
    session: Session = Depends(get_db_session),
) -> DashboardResponse:
    """Return KPI cards with vs-prior-period trends.

    Computes total cases, total loss, active threats, sites investigated,
    unique indicators, and median detection-to-action time for the
    requested period and the immediately preceding period of equal length.

    Args:
        period: Time window preset.
        store: Pre-computed analytics store.
        session: DB session for raw queries.

    Returns:
        Dashboard response with KPI cards.
    """
    start, end = _parse_period(period)
    span_days = (end - start).days
    prev_start = start - timedelta(days=span_days)

    now_dt = datetime.combine(end, datetime.min.time(), tzinfo=UTC)
    start_dt = datetime.combine(start, datetime.min.time(), tzinfo=UTC)
    prev_start_dt = datetime.combine(prev_start, datetime.min.time(), tzinfo=UTC)

    def _count_cases(s: datetime, e: datetime) -> int:
        return (
            session.scalar(select(func.count(cases.c.case_id)).where(cases.c.created_at >= s, cases.c.created_at < e))
            or 0
        )

    def _sum_loss(s: datetime, e: datetime) -> float:
        return float(
            session.scalar(
                select(func.coalesce(func.sum(intake_records.c.loss_amount), 0)).where(
                    intake_records.c.created_at >= s, intake_records.c.created_at < e
                )
            )
            or 0
        )

    cur_cases = _count_cases(start_dt, now_dt)
    prev_cases = _count_cases(prev_start_dt, start_dt)
    cur_loss = _sum_loss(start_dt, now_dt)
    prev_loss = _sum_loss(prev_start_dt, start_dt)

    # Active threats from entity_stats
    active_threats = (
        session.scalar(select(func.count()).select_from(entity_stats).where(entity_stats.c.status == "active")) or 0
    )

    # Unique indicators in period
    cur_indicators = (
        session.scalar(
            select(func.count(indicator_stats.c.indicator_id)).where(indicator_stats.c.first_seen_at >= str(start))
        )
        or 0
    )
    prev_indicators = (
        session.scalar(
            select(func.count(indicator_stats.c.indicator_id)).where(
                indicator_stats.c.first_seen_at >= str(prev_start),
                indicator_stats.c.first_seen_at < str(start),
            )
        )
        or 0
    )

    # Median action time
    action_rows = session.execute(
        select(review_actions.c.created_at, cases.c.created_at.label("case_created"))
        .join(review_queue, review_actions.c.review_id == review_queue.c.review_id)
        .join(cases, review_queue.c.case_id == cases.c.case_id)
        .where(review_actions.c.created_at >= start_dt, review_actions.c.created_at < now_dt)
        .order_by(review_actions.c.created_at)
    ).all()
    if action_rows:
        deltas = []
        for row in action_rows:
            act_time = row[0] if isinstance(row[0], datetime) else datetime.fromisoformat(str(row[0]))
            case_time = row[1] if isinstance(row[1], datetime) else datetime.fromisoformat(str(row[1]))
            if act_time.tzinfo is None:
                act_time = act_time.replace(tzinfo=UTC)
            if case_time.tzinfo is None:
                case_time = case_time.replace(tzinfo=UTC)
            delta_h = (act_time - case_time).total_seconds() / 3600
            if delta_h >= 0:
                deltas.append(delta_h)
        deltas.sort()
        median_hours = deltas[len(deltas) // 2] if deltas else 0.0
    else:
        median_hours = 0.0

    cases_trend, cases_change = _calculate_trend(cur_cases, prev_cases)
    loss_trend, loss_change = _calculate_trend(cur_loss, prev_loss)
    ind_trend, ind_change = _calculate_trend(cur_indicators, prev_indicators)

    kpis = [
        KpiCardItem(label="Total Cases", value=str(cur_cases), trend=cases_trend, change=cases_change),
        KpiCardItem(label="Total Loss", value=f"${cur_loss:,.0f}", trend=loss_trend, change=loss_change),
        KpiCardItem(label="Active Threats", value=str(active_threats), trend="flat", change="Current"),
        KpiCardItem(label="New Indicators", value=str(cur_indicators), trend=ind_trend, change=ind_change),
        KpiCardItem(
            label="Median Action Time",
            value=f"{median_hours:.1f}h",
            trend="flat",
            change="Period median",
        ),
    ]
    return DashboardResponse(kpis=kpis, period_label=period)


# ---------------------------------------------------------------------------
# S3-01  /api/impact/loss-by-taxonomy — treemap data
# ---------------------------------------------------------------------------


@router.get("/loss-by-taxonomy", response_model=list[TaxonomyLossItem])
def get_loss_by_taxonomy(
    session: Session = Depends(get_db_session),
) -> list[TaxonomyLossItem]:
    """Return loss sums grouped by case classification for the treemap.

    Args:
        session: DB session.

    Returns:
        List of taxonomy-label / loss / case-count tuples.
    """
    rows = session.execute(
        select(
            cases.c.classification,
            func.coalesce(func.sum(intake_records.c.loss_amount), 0).label("loss_sum"),
            func.count(func.distinct(cases.c.case_id)).label("case_count"),
        )
        .select_from(cases)
        .outerjoin(intake_records, intake_records.c.case_id == cases.c.case_id)
        .where(cases.c.classification.is_not(None))
        .group_by(cases.c.classification)
        .order_by(func.sum(intake_records.c.loss_amount).desc())
    ).all()

    return [
        TaxonomyLossItem(
            label=str(r[0] or "Unknown"),
            loss_sum=float(r[1] or 0),
            case_count=int(r[2] or 0),
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# S3-01  /api/impact/detection-velocity — proactive vs reactive line chart
# ---------------------------------------------------------------------------


@router.get("/detection-velocity", response_model=list[DetectionVelocityPoint])
def get_detection_velocity(
    period: str = Query("30d", description="Period preset"),
    store: AnalyticsStore = Depends(_get_analytics_store),
) -> list[DetectionVelocityPoint]:
    """Return weekly case counts split by proactive/reactive sources.

    Args:
        period: Time window preset.
        store: Pre-computed analytics store.

    Returns:
        List of weekly detection velocity data points.
    """
    start, end = _parse_period(period)
    kpis = store.list_platform_kpis(period_type="weekly", start_date=start, end_date=end, limit=52)
    return [
        DetectionVelocityPoint(
            period=str(k.get("period_start", "")),
            proactive=int(k.get("proactive_cases", 0)),
            reactive=int(k.get("reactive_cases", 0)),
            total=int(k.get("total_cases", 0)),
        )
        for k in kpis
    ]


# ---------------------------------------------------------------------------
# S3-01  /api/impact/pipeline-funnel — intake→action drop-off
# ---------------------------------------------------------------------------


@router.get("/pipeline-funnel", response_model=list[PipelineFunnelStage])
def get_pipeline_funnel(
    session: Session = Depends(get_db_session),
) -> list[PipelineFunnelStage]:
    """Return pipeline funnel stages: intake → ingestion → classification → review → action.

    Args:
        session: DB session.

    Returns:
        List of funnel stages with counts.
    """
    intake_count = session.scalar(select(func.count(intake_records.c.intake_id))) or 0
    case_count = session.scalar(select(func.count(cases.c.case_id))) or 0
    classified_count = (
        session.scalar(select(func.count(cases.c.case_id)).where(cases.c.classification.is_not(None))) or 0
    )
    reviewed_count = (
        session.scalar(
            select(func.count(cases.c.case_id)).where(cases.c.status.in_(["accepted", "rejected", "escalated"]))
        )
        or 0
    )
    actioned_count = (
        session.scalar(
            select(func.count(func.distinct(review_queue.c.case_id)))
            .select_from(review_actions)
            .join(review_queue, review_actions.c.review_id == review_queue.c.review_id)
        )
        or 0
    )

    return [
        PipelineFunnelStage(stage="Intake", count=intake_count),
        PipelineFunnelStage(stage="Ingestion", count=case_count),
        PipelineFunnelStage(stage="Classification", count=classified_count),
        PipelineFunnelStage(stage="Review", count=reviewed_count),
        PipelineFunnelStage(stage="Action", count=actioned_count),
    ]


# ---------------------------------------------------------------------------
# S3-02  /api/impact/cumulative-indicators — stacked area chart data
# ---------------------------------------------------------------------------


@router.get("/cumulative-indicators", response_model=list[CumulativeIndicatorPoint])
def get_cumulative_indicators(
    period: str = Query("90d", description="Period preset"),
    store: AnalyticsStore = Depends(_get_analytics_store),
) -> list[CumulativeIndicatorPoint]:
    """Return running totals of unique indicators over time, stacked by category.

    Args:
        period: Time window preset.
        store: Pre-computed analytics store.

    Returns:
        List of cumulative indicator data points.
    """
    start, end = _parse_period(period)
    kpis = store.list_platform_kpis(period_type="weekly", start_date=start, end_date=end, limit=52)

    # KPIs track new_indicators per period; build cumulative sums
    cumulative = 0
    results: list[CumulativeIndicatorPoint] = []
    for k in kpis:
        cumulative += int(k.get("new_indicators", 0))
        results.append(
            CumulativeIndicatorPoint(
                period=str(k.get("period_start", "")),
                total=cumulative,
            )
        )
    return results
