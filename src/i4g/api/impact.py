"""Impact analytics API router.

Provides endpoints for the Impact Dashboard: KPI cards with vs-prior-period
trends, loss-by-taxonomy treemap, detection velocity chart, pipeline funnel,
and cumulative indicator time-series.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
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
from i4g.taxonomy.data import TAXONOMY_DEFINITIONS

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


def _engagement_id(request: Request) -> str | None:
    """Extract engagement_id from middleware state.

    Returns the engagement UUID when set, or ``None`` for 'All Engagements'.
    The analytics store interprets ``None`` differently from ``"__global__"``:
    * ``"__global__"`` — aggregate KPI rows (default for unscoped views)
    * A UUID string — per-engagement KPI rows
    * ``None`` — no engagement filter (all rows)
    """
    return getattr(request.state, "engagement_id", None)


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
    code: str = ""
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
    request: Request,
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
    eid = _engagement_id(request)

    def _count_cases(s: datetime, e: datetime) -> int:
        stmt = select(func.count(cases.c.case_id)).where(cases.c.created_at >= s, cases.c.created_at < e)
        if eid:
            stmt = stmt.where(cases.c.engagement_id == eid)
        return session.scalar(stmt) or 0

    def _sum_loss(s: datetime, e: datetime) -> float:
        stmt = select(func.coalesce(func.sum(intake_records.c.loss_amount), 0)).where(
            intake_records.c.created_at >= s, intake_records.c.created_at < e
        )
        if eid:
            stmt = stmt.select_from(intake_records.join(cases, intake_records.c.case_id == cases.c.case_id)).where(
                cases.c.engagement_id == eid
            )
        return float(session.scalar(stmt) or 0)

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
            select(func.count(indicator_stats.c.indicator_id)).where(indicator_stats.c.first_seen_at >= start_dt)
        )
        or 0
    )
    prev_indicators = (
        session.scalar(
            select(func.count(indicator_stats.c.indicator_id)).where(
                indicator_stats.c.first_seen_at >= prev_start_dt,
                indicator_stats.c.first_seen_at < start_dt,
            )
        )
        or 0
    )

    # Median action time
    action_stmt = (
        select(review_actions.c.created_at, cases.c.created_at.label("case_created"))
        .join(review_queue, review_actions.c.review_id == review_queue.c.review_id)
        .join(cases, review_queue.c.case_id == cases.c.case_id)
        .where(review_actions.c.created_at >= start_dt, review_actions.c.created_at < now_dt)
    )
    if eid:
        action_stmt = action_stmt.where(cases.c.engagement_id == eid)
    action_rows = session.execute(action_stmt.order_by(review_actions.c.created_at)).all()
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
    request: Request,
    session: Session = Depends(get_db_session),
) -> list[TaxonomyLossItem]:
    """Return loss sums grouped by case classification for the treemap.

    Args:
        request: Incoming request (engagement context).
        session: DB session.

    Returns:
        List of taxonomy-label / loss / case-count tuples.
    """
    eid = _engagement_id(request)
    stmt = (
        select(
            cases.c.classification,
            func.coalesce(func.sum(intake_records.c.loss_amount), 0).label("loss_sum"),
            func.count(func.distinct(cases.c.case_id)).label("case_count"),
        )
        .select_from(cases)
        .outerjoin(intake_records, intake_records.c.case_id == cases.c.case_id)
        .where(cases.c.classification.is_not(None))
    )
    if eid:
        stmt = stmt.where(cases.c.engagement_id == eid)
    rows = session.execute(
        stmt.group_by(cases.c.classification).order_by(func.sum(intake_records.c.loss_amount).desc())
    ).all()

    return [
        TaxonomyLossItem(
            label=_resolve_taxonomy_label(str(r[0] or "Unknown")),
            code=str(r[0] or "Unknown"),
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
    request: Request,
    period: str = Query("30d", description="Period preset"),
    store: AnalyticsStore = Depends(_get_analytics_store),
) -> list[DetectionVelocityPoint]:
    """Return weekly case counts split by proactive/reactive sources."""
    start, end = _parse_period(period)
    eid = _engagement_id(request)
    kpis = store.list_platform_kpis(
        period_type="weekly",
        start_date=start,
        end_date=end,
        engagement_id=eid or "__global__",
        limit=52,
    )
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
    request: Request,
    session: Session = Depends(get_db_session),
) -> list[PipelineFunnelStage]:
    """Return pipeline funnel stages: intake → ingestion → classification → review → action.

    Args:
        request: Incoming request (engagement context).
        session: DB session.

    Returns:
        List of funnel stages with counts.
    """
    eid = _engagement_id(request)

    intake_q = select(func.count(intake_records.c.intake_id))
    case_q = select(func.count(cases.c.case_id))
    classified_q = select(func.count(cases.c.case_id)).where(cases.c.classification.is_not(None))
    reviewed_q = select(func.count(cases.c.case_id)).where(cases.c.status.in_(["accepted", "rejected", "escalated"]))
    actioned_q = (
        select(func.count(func.distinct(review_queue.c.case_id)))
        .select_from(review_actions)
        .join(review_queue, review_actions.c.review_id == review_queue.c.review_id)
    )
    if eid:
        intake_q = intake_q.select_from(intake_records.join(cases, intake_records.c.case_id == cases.c.case_id)).where(
            cases.c.engagement_id == eid
        )
        case_q = case_q.where(cases.c.engagement_id == eid)
        classified_q = classified_q.where(cases.c.engagement_id == eid)
        reviewed_q = reviewed_q.where(cases.c.engagement_id == eid)
        actioned_q = actioned_q.join(cases, review_queue.c.case_id == cases.c.case_id).where(
            cases.c.engagement_id == eid
        )

    intake_count = session.scalar(intake_q) or 0
    case_count = session.scalar(case_q) or 0
    classified_count = session.scalar(classified_q) or 0
    reviewed_count = session.scalar(reviewed_q) or 0
    actioned_count = session.scalar(actioned_q) or 0

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
    request: Request,
    period: str = Query("90d", description="Period preset"),
    store: AnalyticsStore = Depends(_get_analytics_store),
) -> list[CumulativeIndicatorPoint]:
    """Return running totals of unique indicators over time, stacked by category."""
    start, end = _parse_period(period)
    eid = _engagement_id(request)
    kpis = store.list_platform_kpis(
        period_type="weekly",
        start_date=start,
        end_date=end,
        engagement_id=eid or "__global__",
        limit=52,
    )

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


# ---------------------------------------------------------------------------
# S4-08  /api/impact/taxonomy/sankey — Sankey flow chart data
# ---------------------------------------------------------------------------


class SankeyNode(CamelModel):
    """Node in a Sankey diagram."""

    id: str
    label: str
    code: str = ""
    value: int = 0


class SankeyLink(CamelModel):
    """Link between Sankey nodes."""

    source: str
    target: str
    value: int = 0


class SankeyResponse(CamelModel):
    """Taxonomy Sankey response."""

    nodes: list[SankeyNode] = Field(default_factory=list)
    links: list[SankeyLink] = Field(default_factory=list)


def _build_taxonomy_lookup() -> dict[str, str]:
    """Build a code → display-label mapping from TAXONOMY_DEFINITIONS."""
    lookup: dict[str, str] = {}
    for axis in TAXONOMY_DEFINITIONS.get("axes", []):
        for item in axis.get("items", []):
            lookup[item["code"]] = item["label"]
    return lookup


_TAXONOMY_LABELS: dict[str, str] = _build_taxonomy_lookup()


def _resolve_taxonomy_label(code: str) -> str:
    """Return the human-readable label for a taxonomy code.

    Falls back to a title-cased suffix when the code is not in the registry
    (e.g. ``INTENT.UNKNOWN`` → ``Unknown``).
    """
    if code in _TAXONOMY_LABELS:
        return _TAXONOMY_LABELS[code]
    suffix = code.split(".")[-1] if "." in code else code
    return suffix.replace("_", " ").title()


@router.get("/taxonomy/sankey", response_model=SankeyResponse)
def get_taxonomy_sankey(
    request: Request,
    period: str = Query("90d", description="Period preset"),
    db: Session = Depends(get_db_session),
) -> SankeyResponse:
    """Return Sankey flow data for the fraud taxonomy breakdown.

    Generates a two-level Sankey: category → subcategory, weighted
    by the count of associated cases.

    Args:
        period: Time window preset.
        db: Injected DB session.

    Returns:
        Sankey diagram data with nodes and links.
    """
    start, _ = _parse_period(period)
    eid = _engagement_id(request)
    stmt = (
        select(
            cases.c.classification,
            func.count().label("cnt"),
        )
        .where(cases.c.created_at >= datetime.combine(start, datetime.min.time(), tzinfo=UTC))
        .where(cases.c.classification.is_not(None))
    )
    if eid:
        stmt = stmt.where(cases.c.engagement_id == eid)
    stmt = stmt.group_by(cases.c.classification)
    rows = db.execute(stmt).fetchall()

    node_set: dict[str, int] = {}
    links: list[SankeyLink] = []
    for row in rows:
        code = row.classification or "Unknown"
        parts = code.split(" - ", 1)
        cat_code = parts[0]
        sub_code = parts[1] if len(parts) > 1 else "Other"
        cnt = row.cnt
        node_set[cat_code] = node_set.get(cat_code, 0) + cnt
        sub_key = f"{cat_code}:{sub_code}"
        node_set[sub_key] = node_set.get(sub_key, 0) + cnt
        links.append(SankeyLink(source=cat_code, target=sub_key, value=cnt))

    nodes = [
        SankeyNode(
            id=k,
            label=_resolve_taxonomy_label(k.split(":")[-1]),
            code=k.split(":")[-1],
            value=v,
        )
        for k, v in node_set.items()
    ]
    return SankeyResponse(nodes=nodes, links=links)


# ---------------------------------------------------------------------------
# S4-09  /api/impact/taxonomy/heatmap — taxonomy × time heatmap
# ---------------------------------------------------------------------------


class HeatmapCell(CamelModel):
    """One cell in the taxonomy × time heatmap."""

    category: str
    category_code: str = ""
    period: str
    count: int = 0


@router.get("/taxonomy/heatmap", response_model=list[HeatmapCell])
def get_taxonomy_heatmap(
    request: Request,
    period: str = Query("90d", description="Period preset"),
    granularity: str = Query("week", description="Granularity: day, week, month"),
    db: Session = Depends(get_db_session),
) -> list[HeatmapCell]:
    """Return taxonomy × time heatmap data.

    Each cell represents a (category, time-period) pair with a count of cases.

    Args:
        period: Time window preset.
        granularity: Time granularity.
        db: Injected DB session.

    Returns:
        List of heatmap cells.
    """
    start, end = _parse_period(period)
    eid = _engagement_id(request)
    stmt = select(
        cases.c.classification,
        cases.c.created_at,
    ).where(
        cases.c.created_at >= datetime.combine(start, datetime.min.time(), tzinfo=UTC),
        cases.c.classification.is_not(None),
    )
    if eid:
        stmt = stmt.where(cases.c.engagement_id == eid)
    rows = db.execute(stmt).fetchall()

    cells: dict[tuple[str, str], int] = {}
    for row in rows:
        cat_code = (row.classification or "Unknown").split(" - ")[0]
        dt = row.created_at
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt)
        if granularity == "month":
            bucket = dt.strftime("%Y-%m")
        elif granularity == "day":
            bucket = dt.strftime("%Y-%m-%d")
        else:  # week
            iso = dt.isocalendar()
            bucket = f"{iso[0]}-W{iso[1]:02d}"
        key = (cat_code, bucket)
        cells[key] = cells.get(key, 0) + 1

    return [
        HeatmapCell(category=_resolve_taxonomy_label(k[0]), category_code=k[0], period=k[1], count=v)
        for k, v in sorted(cells.items())
    ]


# ---------------------------------------------------------------------------
# S4-10  /api/impact/taxonomy/trend — taxonomy trend time-series
# ---------------------------------------------------------------------------


class TaxonomyTrendPoint(CamelModel):
    """A single point in a taxonomy trend time-series."""

    period: str
    category: str
    category_code: str = ""
    count: int = 0


@router.get("/taxonomy/trend", response_model=list[TaxonomyTrendPoint])
def get_taxonomy_trend(
    request: Request,
    period: str = Query("90d", description="Period preset"),
    categories: str | None = Query(None, description="Comma-separated category filter"),
    db: Session = Depends(get_db_session),
) -> list[TaxonomyTrendPoint]:
    """Return taxonomy trend data showing category evolution over time.

    Args:
        period: Time window preset.
        categories: Comma-separated filter for specific categories.
        db: Injected DB session.

    Returns:
        List of taxonomy trend data points.
    """
    start, end = _parse_period(period)
    eid = _engagement_id(request)
    stmt = select(
        cases.c.classification,
        cases.c.created_at,
    ).where(
        cases.c.created_at >= datetime.combine(start, datetime.min.time(), tzinfo=UTC),
        cases.c.classification.is_not(None),
    )
    if eid:
        stmt = stmt.where(cases.c.engagement_id == eid)

    if categories:
        cat_list = [c.strip() for c in categories.split(",")]
        stmt = stmt.where(cases.c.classification.in_(cat_list))

    rows = db.execute(stmt).fetchall()

    buckets: dict[tuple[str, str], int] = {}
    for row in rows:
        cat_code = (row.classification or "Unknown").split(" - ")[0]
        dt = row.created_at
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt)
        iso = dt.isocalendar()
        bucket = f"{iso[0]}-W{iso[1]:02d}"
        key = (bucket, cat_code)
        buckets[key] = buckets.get(key, 0) + 1

    return [
        TaxonomyTrendPoint(
            period=k[0],
            category=_resolve_taxonomy_label(k[1]),
            category_code=k[1],
            count=v,
        )
        for k, v in sorted(buckets.items())
    ]


# ---------------------------------------------------------------------------
# S4-11  /api/impact/geography — geographic summary
# ---------------------------------------------------------------------------


class GeographySummary(CamelModel):
    """Country-level geographic aggregation."""

    country: str
    case_count: int = 0
    total_loss: float = 0.0
    victim_count: int = 0


@router.get("/geography", response_model=list[GeographySummary])
def get_geography_summary(
    request: Request,
    period: str = Query("90d", description="Period preset"),
    db: Session = Depends(get_db_session),
) -> list[GeographySummary]:
    """Return geographic summary data aggregated by country.

    Args:
        period: Time window preset.
        db: Injected DB session.

    Returns:
        List of per-country summary objects.
    """
    start, _ = _parse_period(period)
    eid = _engagement_id(request)
    base = intake_records
    if eid:
        base = intake_records.join(cases, intake_records.c.case_id == cases.c.case_id)
    geo_filter = [
        intake_records.c.created_at >= datetime.combine(start, datetime.min.time(), tzinfo=UTC),
        intake_records.c.victim_country.is_not(None),
    ]
    if eid:
        geo_filter.append(cases.c.engagement_id == eid)
    stmt = (
        select(
            intake_records.c.victim_country,
            func.count().label("case_count"),
            func.coalesce(func.sum(intake_records.c.loss_amount), 0).label("total_loss"),
        )
        .select_from(base)
        .where(*geo_filter)
        .group_by(intake_records.c.victim_country)
    )
    rows = db.execute(stmt).fetchall()

    return [
        GeographySummary(
            country=row.victim_country or "Unknown",
            case_count=row.case_count,
            total_loss=float(row.total_loss),
            victim_count=row.case_count,
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# S4-12  /api/impact/geography/{country} — country detail
# ---------------------------------------------------------------------------


class CountryDetailRecord(CamelModel):
    """Detail record for a single country drill-down."""

    case_id: str
    category: str | None = None
    category_code: str | None = None
    loss_amount: float = 0.0
    created_at: str | None = None


class CountryDetailResponse(CamelModel):
    """Country detail response with records and totals."""

    country: str
    total_cases: int = 0
    total_loss: float = 0.0
    records: list[CountryDetailRecord] = Field(default_factory=list)


@router.get("/geography/{country}", response_model=CountryDetailResponse)
def get_geography_detail(
    country: str,
    request: Request,
    period: str = Query("90d", description="Period preset"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db_session),
) -> CountryDetailResponse:
    """Return detailed case records for a specific country.

    Args:
        country: Country code to drill into.
        period: Time window preset.
        limit: Max records returned.
        db: Injected DB session.

    Returns:
        Country detail with individual case records.
    """
    start, _ = _parse_period(period)
    eid = _engagement_id(request)
    detail_filters = [
        intake_records.c.victim_country == country,
        intake_records.c.created_at >= datetime.combine(start, datetime.min.time(), tzinfo=UTC),
    ]
    if eid:
        detail_filters.append(cases.c.engagement_id == eid)
    stmt = (
        select(
            intake_records.c.case_id,
            cases.c.classification,
            intake_records.c.loss_amount,
            intake_records.c.created_at,
        )
        .select_from(intake_records.join(cases, intake_records.c.case_id == cases.c.case_id))
        .where(*detail_filters)
        .limit(limit)
    )
    rows = db.execute(stmt).fetchall()

    records = [
        CountryDetailRecord(
            case_id=str(row.case_id),
            category=_resolve_taxonomy_label(row.classification) if row.classification else None,
            category_code=row.classification,
            loss_amount=float(row.loss_amount or 0),
            created_at=row.created_at.isoformat() if row.created_at else None,
        )
        for row in rows
    ]

    total_loss = sum(r.loss_amount for r in records)
    return CountryDetailResponse(
        country=country,
        total_cases=len(records),
        total_loss=total_loss,
        records=records,
    )


# ---------------------------------------------------------------------------
# S5-22 / S5-23  Victim analytics
# ---------------------------------------------------------------------------


class VictimDemographicBreakdown(CamelModel):
    """Single bucket in a demographics breakdown."""

    label: str
    count: int
    loss_sum: float = 0.0
    percentage: float = 0.0


class VictimAnalyticsResponse(CamelModel):
    """Aggregate victim demographics for the Impact Dashboard."""

    total_victims: int
    by_age_range: list[VictimDemographicBreakdown]
    by_country: list[VictimDemographicBreakdown]
    by_contact_channel: list[VictimDemographicBreakdown]


@router.get("/victims", response_model=VictimAnalyticsResponse)
def get_victim_analytics(
    request: Request,
    period: str = Query("90d", description="Time period: 30d, 90d, 1y, all"),
    db: Session = Depends(get_db_session),
) -> VictimAnalyticsResponse:
    """Return aggregate victim demographics (age range, country, contact channel).

    All data is aggregated — no individual-level PII is returned.

    Args:
        period: Time window for analysis.
        db: Injected database session.

    Returns:
        Victim analytics with breakdowns by age, country, and channel.
    """
    start, _ = _parse_period(period)
    start_dt = datetime.combine(start, datetime.min.time(), tzinfo=UTC)
    eid = _engagement_id(request)

    base_filter = [intake_records.c.created_at >= start_dt]
    base_from = intake_records
    if eid:
        base_from = intake_records.join(cases, intake_records.c.case_id == cases.c.case_id)
        base_filter.append(cases.c.engagement_id == eid)

    # Total count
    total_stmt = select(func.count()).select_from(base_from).where(*base_filter)
    total_victims = db.execute(total_stmt).scalar() or 0

    # By age range
    age_stmt = (
        select(
            intake_records.c.victim_age_range,
            func.count().label("cnt"),
            func.coalesce(func.sum(intake_records.c.loss_amount), 0).label("loss"),
        )
        .select_from(base_from)
        .where(*base_filter, intake_records.c.victim_age_range.isnot(None))
        .group_by(intake_records.c.victim_age_range)
        .order_by(func.count().desc())
    )
    age_rows = db.execute(age_stmt).fetchall()
    by_age = [
        VictimDemographicBreakdown(
            label=row.victim_age_range or "Unknown",
            count=row.cnt,
            loss_sum=float(row.loss or 0),
            percentage=round(row.cnt / total_victims * 100, 1) if total_victims else 0,
        )
        for row in age_rows
    ]

    # By country
    country_stmt = (
        select(
            intake_records.c.victim_country,
            func.count().label("cnt"),
            func.coalesce(func.sum(intake_records.c.loss_amount), 0).label("loss"),
        )
        .select_from(base_from)
        .where(*base_filter, intake_records.c.victim_country.isnot(None))
        .group_by(intake_records.c.victim_country)
        .order_by(func.count().desc())
        .limit(50)
    )
    country_rows = db.execute(country_stmt).fetchall()
    by_country = [
        VictimDemographicBreakdown(
            label=row.victim_country or "Unknown",
            count=row.cnt,
            loss_sum=float(row.loss or 0),
            percentage=round(row.cnt / total_victims * 100, 1) if total_victims else 0,
        )
        for row in country_rows
    ]

    # By contact channel
    channel_stmt = (
        select(
            intake_records.c.contact_channel,
            func.count().label("cnt"),
            func.coalesce(func.sum(intake_records.c.loss_amount), 0).label("loss"),
        )
        .select_from(base_from)
        .where(*base_filter, intake_records.c.contact_channel.isnot(None))
        .group_by(intake_records.c.contact_channel)
        .order_by(func.count().desc())
    )
    channel_rows = db.execute(channel_stmt).fetchall()
    by_channel = [
        VictimDemographicBreakdown(
            label=row.contact_channel or "Unknown",
            count=row.cnt,
            loss_sum=float(row.loss or 0),
            percentage=round(row.cnt / total_victims * 100, 1) if total_victims else 0,
        )
        for row in channel_rows
    ]

    return VictimAnalyticsResponse(
        total_victims=total_victims,
        by_age_range=by_age,
        by_country=by_country,
        by_contact_channel=by_channel,
    )
