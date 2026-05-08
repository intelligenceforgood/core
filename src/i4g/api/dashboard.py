"""Dashboard overview endpoints for analyst console."""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from i4g.api.auth import require_token
from i4g.api.camel import CamelModel
from i4g.api.response_models import DashboardOverviewResponse
from i4g.api.review_deps import get_db_session
from i4g.store.sql import (
    cases,
    entities,
    review_actions,
    review_queue,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"], dependencies=[Depends(require_token)])


def _get_active_investigations(session: Session, engagement_id: str | None = None) -> dict[str, str]:
    """Count open cases in the review queue."""
    base = select(func.count(review_queue.c.review_id)).where(
        review_queue.c.status.not_in(["closed", "accepted", "rejected"])
    )
    if engagement_id:
        base = base.join(cases, cases.c.case_id == review_queue.c.case_id).where(cases.c.engagement_id == engagement_id)
    count = session.scalar(base) or 0

    # Compare to last week
    now = datetime.now(UTC)
    last_week = now - timedelta(days=7)

    prev = (
        select(func.count(review_queue.c.review_id))
        .where(review_queue.c.status.not_in(["closed", "resolved"]))
        .where(review_queue.c.queued_at < last_week)
    )
    if engagement_id:
        prev = prev.join(cases, cases.c.case_id == review_queue.c.case_id).where(cases.c.engagement_id == engagement_id)
    prev_count = session.scalar(prev) or 0

    change_pct = 0
    if prev_count > 0:
        change_pct = int(((count - prev_count) / prev_count) * 100)

    change_str = f"{change_pct:+.0f}% vs last week"
    if prev_count == 0:
        change_str = "No baseline"

    return {"label": "Active investigations", "value": str(count), "change": change_str}


def _get_new_leads(session: Session, engagement_id: str | None = None) -> dict[str, str]:
    """Count new cases created in the last 7 days."""
    now = datetime.now(UTC)
    start_dt = now - timedelta(days=7)

    base = select(func.count(review_queue.c.case_id)).where(review_queue.c.queued_at >= start_dt)
    if engagement_id:
        base = base.join(cases, cases.c.case_id == review_queue.c.case_id).where(cases.c.engagement_id == engagement_id)
    count = session.scalar(base) or 0

    return {"label": "New leads this week", "value": str(count), "change": f"+{count} sourced automatically"}


def _get_cases_at_risk(session: Session, engagement_id: str | None = None) -> dict[str, str]:
    """Count high priority cases."""
    base = (
        select(func.count(review_queue.c.review_id))
        .where(review_queue.c.priority.in_(["high", "critical"]))
        .where(review_queue.c.status.not_in(["closed", "resolved"]))
    )
    if engagement_id:
        base = base.join(cases, cases.c.case_id == review_queue.c.case_id).where(cases.c.engagement_id == engagement_id)
    count = session.scalar(base) or 0

    return {"label": "Cases at risk", "value": str(count), "change": "Need follow-up within 24h"}


def _get_recent_activity(session: Session) -> list[dict[str, str]]:
    """Get recent review actions."""
    rows = session.execute(
        select(review_actions.c.action_id, review_actions.c.action, review_actions.c.actor, review_actions.c.created_at)
        .order_by(desc(review_actions.c.created_at))
        .limit(5)
    ).all()

    activities = []
    now = datetime.now(UTC)

    for row in rows:
        # Calculate relative time string like "10m ago"
        dt = row.created_at
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)

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


def _get_engagement_completion(session: Session, engagement_id: str | None = None) -> dict[str, str]:
    """Calculate engagement completion percentage."""
    if not engagement_id:
        return {"label": "Engagement completion", "value": "N/A", "change": "No engagement selected"}

    total = session.scalar(select(func.count(cases.c.case_id)).where(cases.c.engagement_id == engagement_id)) or 0
    if total == 0:
        return {"label": "Engagement completion", "value": "0%", "change": "0 cases"}

    closed = (
        session.scalar(
            select(func.count(cases.c.case_id))
            .where(cases.c.engagement_id == engagement_id)
            .where(cases.c.status.in_(["closed", "resolved", "accepted", "rejected"]))
        )
        or 0
    )
    pct = int((closed / total) * 100)
    return {"label": "Engagement completion", "value": f"{pct}%", "change": f"{closed} of {total} cases closed"}


def _get_loss_linkages(session: Session, engagement_id: str | None = None) -> dict[str, str]:
    """Calculate loss linkages."""
    from i4g.store.sql import cases, financial_damage_claims

    base = select(func.count(financial_damage_claims.c.claim_id))
    if engagement_id:
        base = base.join(cases, cases.c.case_id == financial_damage_claims.c.case_id).where(
            cases.c.engagement_id == engagement_id
        )

    count = session.scalar(base) or 0
    return {"label": "Loss linkages", "value": str(count), "change": "Identified from claims"}


def _get_campaign_risk_scores(session: Session, engagement_id: str | None = None) -> dict[str, str]:
    """Calculate average campaign risk score."""
    from i4g.store.sql import campaign_stats, cases, threat_campaign_cases

    base = select(func.avg(campaign_stats.c.risk_score))
    if engagement_id:
        base = (
            base.join(threat_campaign_cases, threat_campaign_cases.c.campaign_id == campaign_stats.c.campaign_id)
            .join(cases, cases.c.case_id == threat_campaign_cases.c.case_id)
            .where(cases.c.engagement_id == engagement_id)
        )

    avg_score = session.scalar(base)
    val = f"{avg_score:.1f}" if avg_score is not None else "0.0"
    return {"label": "Avg Campaign Risk", "value": val, "change": "Aggregate across active threats"}


def _get_alerts(session: Session, engagement_id: str | None = None) -> list[dict[str, str]]:
    """Get alerts based on high priority cases created recently and active campaigns."""
    from i4g.store.sql import cases, threat_campaign_cases, threat_campaigns

    alerts = []
    now = datetime.now(UTC)

    # 1. High priority cases
    case_base = select(cases.c.case_id, cases.c.classification, cases.c.created_at).where(
        cases.c.classification.in_(["scam", "fraud", "phishing"])
    )
    if engagement_id:
        case_base = case_base.where(cases.c.engagement_id == engagement_id)
    case_rows = session.execute(case_base.order_by(desc(cases.c.created_at)).limit(3)).all()

    for row in case_rows:
        dt = row.created_at
        if dt and dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        diff = now - dt if dt else timedelta(minutes=5)
        minutes = int(diff.total_seconds() / 60)
        time_str = f"{minutes}m ago"

        alerts.append(
            {
                "id": f"alert-case-{row.case_id}",
                "title": f"High confidence {row.classification}",
                "detail": f"Case {row.case_id} detected recently",
                "time": time_str,
                "variant": "danger",
            }
        )

    # 2. Campaign alerts
    campaign_base = select(
        threat_campaigns.c.campaign_id, threat_campaigns.c.name, threat_campaigns.c.created_at
    ).where(threat_campaigns.c.status == "active")
    if engagement_id:
        campaign_base = (
            campaign_base.join(
                threat_campaign_cases, threat_campaign_cases.c.campaign_id == threat_campaigns.c.campaign_id
            )
            .join(cases, cases.c.case_id == threat_campaign_cases.c.case_id)
            .where(cases.c.engagement_id == engagement_id)
        )
    campaign_rows = session.execute(campaign_base.order_by(desc(threat_campaigns.c.created_at)).limit(3)).all()

    for row in campaign_rows:
        dt = row.created_at
        if dt and dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        diff = now - dt if dt else timedelta(minutes=5)
        minutes = int(diff.total_seconds() / 60)
        time_str = f"{minutes}m ago" if minutes < 60 else f"{minutes // 60}h ago"

        alerts.append(
            {
                "id": f"alert-campaign-{row.campaign_id}",
                "title": f"Active Campaign: {row.name}",
                "detail": f"Campaign {row.campaign_id[:8]} requires attention",
                "time": time_str,
                "variant": "warning",
            }
        )

    return alerts


@router.get("/overview", response_model=DashboardOverviewResponse)
def get_dashboard_overview(request: Request, session: Session = Depends(get_db_session)):
    """Return live dashboard metrics from the database."""
    engagement_id = getattr(request.state, "engagement_id", None)
    metrics = [
        _get_active_investigations(session, engagement_id=engagement_id),
        _get_new_leads(session, engagement_id=engagement_id),
        _get_cases_at_risk(session, engagement_id=engagement_id),
        _get_engagement_completion(session, engagement_id=engagement_id),
        _get_loss_linkages(session, engagement_id=engagement_id),
        _get_campaign_risk_scores(session, engagement_id=engagement_id),
    ]

    activity = _get_recent_activity(session)
    alerts = _get_alerts(session, engagement_id=engagement_id)

    # TODO: Wire to a task/reminder system when available.
    reminders: list[dict[str, str]] = []

    return {
        "metrics": metrics,
        "alerts": alerts,
        "activity": activity,
        "reminders": reminders,
    }


# ---------------------------------------------------------------------------
# Processing progress — ingestion pipeline health at a glance
# ---------------------------------------------------------------------------


class ProcessingProgressResponse(CamelModel):
    """Data pipeline processing progress."""

    total_cases: int = 0
    classified_cases: int = 0
    cases_with_entities: int = 0


@router.get("/processing-progress", response_model=ProcessingProgressResponse)
def get_processing_progress(request: Request, session: Session = Depends(get_db_session)) -> ProcessingProgressResponse:
    """Return processing pipeline progress counts."""
    engagement_id = getattr(request.state, "engagement_id", None)

    total_q = select(func.count()).select_from(cases).where(cases.c.is_deleted.is_(False))
    classified_q = (
        select(func.count())
        .select_from(cases)
        .where(cases.c.is_deleted.is_(False))
        .where(cases.c.classification_status == "classified")
    )
    if engagement_id:
        total_q = total_q.where(cases.c.engagement_id == engagement_id)
        classified_q = classified_q.where(cases.c.engagement_id == engagement_id)

    total = session.execute(total_q).scalar() or 0
    classified = session.execute(classified_q).scalar() or 0

    entities_q = select(func.count(func.distinct(entities.c.case_id)))
    if engagement_id:
        entities_q = entities_q.join(cases, cases.c.case_id == entities.c.case_id).where(
            cases.c.engagement_id == engagement_id
        )
    with_entities = session.execute(entities_q).scalar() or 0

    return ProcessingProgressResponse(
        total_cases=total,
        classified_cases=classified,
        cases_with_entities=with_entities,
    )
