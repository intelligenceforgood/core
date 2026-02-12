"""Dashboard overview endpoints for analyst console."""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from i4g.api.auth import require_token
from i4g.api.response_models import DashboardOverviewResponse
from i4g.api.review_deps import get_db_session
from i4g.store.sql import (
    review_queue,
    review_actions,
    scam_records,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"], dependencies=[Depends(require_token)])


def _get_active_investigations(session: Session) -> dict[str, str]:
    """Count open cases in the review queue."""
    count = (
        session.scalar(
            select(func.count(review_queue.c.review_id)).where(
                review_queue.c.status.not_in(["closed", "accepted", "rejected"])
            )
        )
        or 0
    )

    # Compare to last week
    now = datetime.now(timezone.utc)
    last_week = now - timedelta(days=7)

    prev_count = (
        session.scalar(
            select(func.count(review_queue.c.review_id))
            .where(review_queue.c.status.not_in(["closed", "resolved"]))
            .where(review_queue.c.queued_at < last_week)
        )
        or 0
    )

    change_pct = 0
    if prev_count > 0:
        change_pct = int(((count - prev_count) / prev_count) * 100)

    change_str = f"{change_pct:+.0f}% vs last week"
    if prev_count == 0:
        change_str = "No baseline"

    return {"label": "Active investigations", "value": str(count), "change": change_str}


def _get_new_leads(session: Session) -> dict[str, str]:
    """Count new cases created in the last 7 days."""
    now = datetime.now(timezone.utc)
    start_dt = now - timedelta(days=7)

    # Use review_queue as proxy for cases in local mode if 'cases' table missing or mapped
    # The 'cases' table exists in SQL metadata but might not be in SQLite if relying on ReviewStore init.
    # We switch to review_queue here for consistency in the simple stack.
    count = session.scalar(select(func.count(review_queue.c.case_id)).where(review_queue.c.queued_at >= start_dt)) or 0

    return {"label": "New leads this week", "value": str(count), "change": f"+{count} sourced automatically"}


def _get_cases_at_risk(session: Session) -> dict[str, str]:
    """Count high priority cases."""
    count = (
        session.scalar(
            select(func.count(review_queue.c.review_id))
            .where(review_queue.c.priority.in_(["high", "critical"]))
            .where(review_queue.c.status.not_in(["closed", "resolved"]))
        )
        or 0
    )

    return {"label": "Cases at risk", "value": str(count), "change": "Need follow-up within 24h"}


def _get_recent_activity(session: Session) -> list[dict[str, str]]:
    """Get recent review actions."""
    rows = session.execute(
        select(review_actions.c.action_id, review_actions.c.action, review_actions.c.actor, review_actions.c.created_at)
        .order_by(desc(review_actions.c.created_at))
        .limit(5)
    ).all()

    activities = []
    now = datetime.now(timezone.utc)

    for row in rows:
        # Calculate relative time string like "10m ago"
        dt = row.created_at
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        diff = now - dt
        minutes = int(diff.total_seconds() / 60)
        when_str = f"{minutes}m ago"
        if minutes > 60:
            hours = minutes // 60
            when_str = f"{hours}h ago"
        if minutes > 1440:
            days = minutes // 1440
            when_str = f"{days}d ago"

        activities.append(
            {
                "id": row.action_id,
                "title": f"Action: {row.action}",
                "actor": row.actor or "System",
                "when": when_str,
            }
        )

    return activities


def _get_alerts(session: Session) -> list[dict[str, str]]:
    """Get alerts based on high priority cases created recently."""
    # Use scam_records instead of cases since 'cases' table is missing in local mode
    rows = session.execute(
        select(scam_records.c.case_id, scam_records.c.classification, scam_records.c.created_at)
        .where(scam_records.c.classification.in_(["scam", "fraud", "phishing"]))  # Example filters
        .order_by(desc(scam_records.c.created_at))
        .limit(3)
    ).all()

    alerts = []
    now = datetime.now(timezone.utc)

    for row in rows:
        dt = row.created_at
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        diff = now - dt
        minutes = int(diff.total_seconds() / 60)
        time_str = f"{minutes}m ago"

        alerts.append(
            {
                "id": f"alert-{row.case_id}",
                "title": f"High confidence {row.classification}",
                "detail": f"Case {row.case_id} detected recently",
                "time": time_str,
                "variant": "danger",
            }
        )

    if not alerts:
        # Empty state or generic
        return []

    return alerts


@router.get("/overview", response_model=DashboardOverviewResponse)
def get_dashboard_overview(session: Session = Depends(get_db_session)):
    """Return live dashboard metrics from the database."""
    metrics = [
        _get_active_investigations(session),
        _get_new_leads(session),
        _get_cases_at_risk(session),
    ]

    activity = _get_recent_activity(session)
    alerts = _get_alerts(session)

    # TODO: Wire to a task/reminder system when available.
    reminders: list[dict[str, str]] = []

    return {
        "metrics": metrics,
        "alerts": alerts,
        "activity": activity,
        "reminders": reminders,
    }
