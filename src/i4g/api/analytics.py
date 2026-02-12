"""Expose real analytics payloads for the console overview page."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from i4g.api.auth import require_token
from i4g.api.response_models import AnalyticsOverviewResponse
from i4g.api.review_deps import get_db_session
from i4g.store.sql import (
    cases,
    review_queue,
    review_actions,
    intake_records,
    ingestion_runs,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["analytics"], dependencies=[Depends(require_token)])


def _calculate_trend(current: float, previous: float) -> tuple[str, str]:
    """Calculate trend direction and human-readable change string."""
    if previous == 0:
        if current == 0:
            return "flat", "No change"
        return "up", "Requires baseline"

    diff = current - previous
    pct_change = (diff / previous) * 100

    direction = "flat"
    if diff > 0:
        direction = "up"
    elif diff < 0:
        direction = "down"

    return direction, f"{diff:+.1f} ({pct_change:+.1f}%) vs prev"


def _get_metric_detection_rate(session: Session, now: datetime) -> dict[str, Any]:
    """Calculate detection rate (Risky Cases / Total Cases)."""
    # Time windows
    window_days = 30
    current_start = now - timedelta(days=window_days)
    prev_start = current_start - timedelta(days=window_days)

    def query_rate(start_dt: datetime, end_dt: datetime) -> float:
        total = (
            session.scalar(
                select(func.count(cases.c.case_id))
                .where(cases.c.created_at >= start_dt)
                .where(cases.c.created_at < end_dt)
            )
            or 0
        )
        if total == 0:
            return 0.0

        # Assuming 'benign' is safe, everything else is a detection
        detected = (
            session.scalar(
                select(func.count(cases.c.case_id))
                .where(cases.c.created_at >= start_dt)
                .where(cases.c.created_at < end_dt)
                .where(cases.c.classification != "benign")
                .where(cases.c.classification.is_not(None))
            )
            or 0
        )

        return (detected / total) * 100

    current_val = query_rate(current_start, now)
    prev_val = query_rate(prev_start, current_start)

    trend, change_text = _calculate_trend(current_val, prev_val)

    return {
        "id": "metric-detection-rate",
        "label": "Detection rate",
        "value": f"{current_val:.1f}%",
        "change": change_text,
        "trend": trend,
    }


def _get_metric_time_to_action(session: Session, now: datetime) -> dict[str, Any]:
    """Calculate median time to action (Action Time - Case Creation)."""
    # Join review actions to cases to get time difference
    window_days = 7
    start_dt = now - timedelta(days=window_days)
    prev_start = start_dt - timedelta(days=window_days)

    def calc_median_hours(start: datetime, end: datetime) -> float:
        rows = session.execute(
            select(review_actions.c.created_at, cases.c.created_at)
            .select_from(review_actions)
            .join(review_queue, review_actions.c.review_id == review_queue.c.review_id)
            .join(cases, review_queue.c.case_id == cases.c.case_id)
            .where(review_actions.c.created_at >= start)
            .where(review_actions.c.created_at < end)
        ).all()

        diffs = []
        for act_at, case_at in rows:
            if act_at and case_at:
                # Ensure timezone awareness compatibility
                if act_at.tzinfo is None:
                    act_at = act_at.replace(tzinfo=timezone.utc)
                if case_at.tzinfo is None:
                    case_at = case_at.replace(tzinfo=timezone.utc)
                diffs.append((act_at - case_at).total_seconds() / 3600.0)

        if not diffs:
            return 0.0

        diffs.sort()
        mid = len(diffs) // 2
        return diffs[mid]

    current_val = calc_median_hours(start_dt, now)
    prev_val = calc_median_hours(prev_start, start_dt)

    trend_dir = "flat"
    if current_val < prev_val and current_val > 0:
        trend_dir = "up"  # Good (lower is better)
    elif current_val > prev_val:
        trend_dir = "down"  # Bad

    diff = current_val - prev_val

    return {
        "id": "metric-time-to-action",
        "label": "Median time to action",
        "value": f"{current_val:.1f}h",
        "change": f"{diff:+.1f}h vs last week",
        "trend": trend_dir,
    }


def _get_metric_proactive(session: Session, now: datetime) -> dict[str, Any]:
    """Count proactive interventions (non-user-reports)."""
    window_days = 7
    current_start = now - timedelta(days=window_days)
    prev_start = current_start - timedelta(days=window_days)

    def count_proactive(start: datetime, end: datetime) -> int:
        return (
            session.scalar(
                select(func.count(cases.c.case_id))
                .where(cases.c.created_at >= start)
                .where(cases.c.created_at < end)
                .where(cases.c.source_type != "user-report")
            )
            or 0
        )

    curr = count_proactive(current_start, now)
    prev = count_proactive(prev_start, current_start)

    trend, change = _calculate_trend(float(curr), float(prev))

    return {
        "id": "metric-proactive",
        "label": "Proactive interventions",
        "value": str(curr),
        "change": change,
        "trend": trend,
    }


# SLA thresholds (hours): high/critical → 24 h, medium/low → 48 h
_SLA_HOURS = {"critical": 24, "high": 24, "medium": 48, "low": 48}


def _get_metric_sla(session: Session, now: datetime) -> dict[str, Any]:
    """SLA adherence — percentage of reviews actioned within their SLA window.

    Computes from ``review_queue`` join ``review_actions`` over the last 30 days.
    """
    window_start = now - timedelta(days=30)

    rows = session.execute(
        select(
            review_queue.c.priority,
            review_queue.c.queued_at,
            func.min(review_actions.c.created_at).label("first_action_at"),
        )
        .select_from(
            review_queue.outerjoin(
                review_actions, review_queue.c.review_id == review_actions.c.review_id
            )
        )
        .where(review_queue.c.queued_at >= window_start)
        .group_by(review_queue.c.review_id, review_queue.c.priority, review_queue.c.queued_at)
    ).all()

    if not rows:
        return {
            "id": "metric-sla",
            "label": "SLA adherence",
            "value": "N/A",
            "change": "No data",
            "trend": "flat",
        }

    met = 0
    total = len(rows)
    for row in rows:
        prio = row.priority or "medium"
        threshold_h = _SLA_HOURS.get(prio, 48)
        first_action = row.first_action_at
        queued = row.queued_at
        if first_action and queued:
            if first_action.tzinfo is None:
                first_action = first_action.replace(tzinfo=timezone.utc)
            if queued.tzinfo is None:
                queued = queued.replace(tzinfo=timezone.utc)
            if (first_action - queued).total_seconds() <= threshold_h * 3600:
                met += 1
        elif first_action is None:
            # No action yet — check if still within window
            if queued.tzinfo is None:
                queued = queued.replace(tzinfo=timezone.utc)
            if (now - queued).total_seconds() <= threshold_h * 3600:
                met += 1

    pct = (met / total) * 100 if total else 0
    trend = "up" if pct >= 90 else "down" if pct < 70 else "flat"

    return {
        "id": "metric-sla",
        "label": "SLA adherence",
        "value": f"{pct:.0f}%",
        "change": f"{met}/{total} within target",
        "trend": trend,
    }


# Country-code → region mapping for geography breakdown
_REGION_MAP: dict[str, str] = {
    "US": "North America", "CA": "North America", "MX": "North America",
    "GB": "Europe", "DE": "Europe", "FR": "Europe", "ES": "Europe",
    "IT": "Europe", "NL": "Europe", "SE": "Europe", "NO": "Europe",
    "CH": "Europe", "AT": "Europe", "PL": "Europe", "BE": "Europe",
    "BR": "LATAM", "AR": "LATAM", "CO": "LATAM", "CL": "LATAM",
    "PE": "LATAM", "EC": "LATAM", "VE": "LATAM",
    "CN": "Asia-Pacific", "JP": "Asia-Pacific", "KR": "Asia-Pacific",
    "IN": "Asia-Pacific", "AU": "Asia-Pacific", "NZ": "Asia-Pacific",
    "SG": "Asia-Pacific", "PH": "Asia-Pacific", "TH": "Asia-Pacific",
    "ID": "Asia-Pacific", "MY": "Asia-Pacific", "VN": "Asia-Pacific",
    "NG": "Africa", "ZA": "Africa", "KE": "Africa", "GH": "Africa",
    "EG": "Africa", "ET": "Africa",
}
_ALL_REGIONS = ["North America", "Europe", "LATAM", "Asia-Pacific", "Africa"]


def _get_geography_breakdown(session: Session) -> list[dict[str, Any]]:
    """Derive geography from ``victim_country`` in scam_records metadata."""
    from i4g.store.sql import scam_records

    rows = session.execute(select(scam_records.c.metadata)).all()
    region_counts: dict[str, int] = {r: 0 for r in _ALL_REGIONS}

    for (meta_raw,) in rows:
        if not meta_raw:
            continue
        meta = meta_raw
        if isinstance(meta, str):
            try:
                import json
                meta = json.loads(meta)
            except (ValueError, TypeError):
                continue
        if not isinstance(meta, dict):
            continue
        country = meta.get("victim_country", "")
        region = _REGION_MAP.get(country, "")
        if region:
            region_counts[region] += 1

    return [{"region": r, "value": region_counts[r]} for r in _ALL_REGIONS]


@router.get("/overview", summary="Return live analytics trends", response_model=AnalyticsOverviewResponse)
def get_analytics_overview(session: Session = Depends(get_db_session)) -> dict[str, object]:
    """Return the analytics payload populated from the database."""

    now = datetime.now(timezone.utc)

    # 1. Top Metrics
    metrics = [
        _get_metric_detection_rate(session, now),
        _get_metric_time_to_action(session, now),
        _get_metric_proactive(session, now),
        _get_metric_sla(session, now),
    ]

    # 2. Daily Series (Last 7 days)
    series = []
    for i in range(6, -1, -1):
        day_start = now - timedelta(days=i)
        day_start = day_start.replace(hour=0, minute=0, second=0, microsecond=0)
        next_day = day_start + timedelta(days=1)

        # Count risky cases
        val = (
            session.scalar(
                select(func.count(cases.c.case_id))
                .where(cases.c.created_at >= day_start)
                .where(cases.c.created_at < next_day)
                .where(cases.c.classification != "benign")
            )
            or 0
        )

        series.append({"label": day_start.strftime("%a"), "value": val})

    # 3. Pipeline Breakdown
    # Intake -> Data fusion -> Human review -> Policy -> Action
    cnt_intake = session.scalar(select(func.count(intake_records.c.intake_id))) or 0
    cnt_fusion = session.scalar(select(func.count(ingestion_runs.c.run_id))) or 0  # Proxy
    cnt_review = session.scalar(select(func.count(review_queue.c.review_id))) or 0
    cnt_action = session.scalar(select(func.count(review_actions.c.action_id))) or 0

    pipeline = [
        {"label": "Intake", "value": cnt_intake},
        {"label": "Data fusion", "value": cnt_fusion},
        {"label": "Human review", "value": cnt_review},
        {"label": "Policy", "value": cnt_review},  # Proxy
        {"label": "Action", "value": cnt_action},
    ]

    # 4. Weekly Incidents (Last 5 weeks)
    weekly = []
    for i in range(4, -1, -1):  # 5 weeks
        week_start = now - timedelta(weeks=i)
        # Find start of week
        start_of_week = week_start - timedelta(days=week_start.weekday())
        next_week = start_of_week + timedelta(weeks=1)

        incidents = (
            session.scalar(
                select(func.count(cases.c.case_id))
                .where(cases.c.created_at >= start_of_week)
                .where(cases.c.created_at < next_week)
            )
            or 0
        )

        interventions = (
            session.scalar(
                select(func.count(review_actions.c.action_id))
                .where(review_actions.c.created_at >= start_of_week)
                .where(review_actions.c.created_at < next_week)
            )
            or 0
        )

        week_label = f"W{start_of_week.isocalendar()[1]}"
        weekly.append({"week": week_label, "incidents": incidents, "interventions": interventions})

    # 5. Geography — derive from victim_country in case metadata
    geography = _get_geography_breakdown(session)

    return {
        "metrics": metrics,
        "detectionRateSeries": series,
        "pipelineBreakdown": pipeline,
        "geographyBreakdown": geography,
        "weeklyIncidents": weekly,
    }
