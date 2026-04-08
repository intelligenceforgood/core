"""Engagement CRUD, leaderboard, and analytics export API router."""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from i4g.api.auth import require_role, require_token
from i4g.api.camel import CamelModel
from i4g.services.factories import build_engagement_store
from i4g.settings import get_settings
from i4g.store.engagement_store import EngagementStore
from i4g.store.sql import session_factory as build_sql_session_factory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/engagements", tags=["engagements"], dependencies=[Depends(require_token)])


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


def get_engagement_store() -> EngagementStore:
    return build_engagement_store()


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class EngagementCreate(BaseModel):
    name: str
    description: str | None = None
    status: str = "draft"
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    metadata: dict[str, Any] | None = None


class EngagementUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    metadata: dict[str, Any] | None = None


class CaseAssignment(BaseModel):
    case_ids: list[str]


class EngagementResponse(CamelModel):
    engagement_id: str
    name: str
    description: str | None = None
    status: str
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    created_by: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class EngagementSummaryResponse(EngagementResponse):
    case_count: int = 0
    cases_reviewed: int = 0
    cases_remaining: int = 0
    review_completion_pct: float = 0.0


class EngagementExtendedSummaryResponse(EngagementSummaryResponse):
    classification_distribution: dict[str, int] = {}
    top_classifications: list[str] = []
    analyst_count: int = 0
    days_elapsed: int | None = None
    days_remaining: int | None = None
    avg_review_time_hours: float | None = None


class LeaderboardEntry(CamelModel):
    rank: int
    analyst_email: str
    cases_reviewed: int
    avg_review_time_seconds: float | None = None
    classification_accuracy: float = 0.0
    risk_score_mae: float | None = None
    actions_logged: int = 0
    last_activity_at: datetime | None = None
    composite_score: float = 0.0


class LeaderboardResponse(CamelModel):
    engagement_id: str
    entries: list[LeaderboardEntry]
    total_analysts: int


class CaseAssignmentResult(CamelModel):
    count: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", status_code=status.HTTP_201_CREATED)
def create_engagement(
    body: EngagementCreate,
    user: dict[str, str] = Depends(require_role("manager")),
    store: EngagementStore = Depends(get_engagement_store),
) -> EngagementResponse:
    try:
        eng = store.create(
            name=body.name,
            description=body.description,
            status=body.status,
            starts_at=body.starts_at,
            ends_at=body.ends_at,
            created_by=user.get("username") or user.get("sub", ""),
            metadata=body.metadata,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return EngagementResponse(**eng)


@router.get("")
def list_engagements(
    status_filter: str | None = None,
    limit: int = 100,
    offset: int = 0,
    user: dict[str, str] = Depends(require_role("analyst")),
    store: EngagementStore = Depends(get_engagement_store),
) -> list[EngagementResponse]:
    return [EngagementResponse(**e) for e in store.list(status=status_filter, limit=limit, offset=offset)]


@router.get("/{engagement_id}")
def get_engagement(
    engagement_id: str,
    user: dict[str, str] = Depends(require_role("analyst")),
    store: EngagementStore = Depends(get_engagement_store),
) -> EngagementResponse:
    eng = store.get(engagement_id)
    if eng is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Engagement not found")
    return EngagementResponse(**eng)


@router.patch("/{engagement_id}")
def update_engagement(
    engagement_id: str,
    body: EngagementUpdate,
    user: dict[str, str] = Depends(require_role("manager")),
    store: EngagementStore = Depends(get_engagement_store),
) -> EngagementResponse:
    update_fields = body.model_dump(exclude_unset=True)
    try:
        eng = store.update(engagement_id, **update_fields)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    if eng is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Engagement not found")
    return EngagementResponse(**eng)


@router.delete("/{engagement_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_engagement(
    engagement_id: str,
    user: dict[str, str] = Depends(require_role("admin")),
    store: EngagementStore = Depends(get_engagement_store),
) -> None:
    eng = store.archive(engagement_id)
    if eng is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Engagement not found")


@router.post("/{engagement_id}/cases")
def assign_cases(
    engagement_id: str,
    body: CaseAssignment,
    user: dict[str, str] = Depends(require_role("manager")),
    store: EngagementStore = Depends(get_engagement_store),
) -> CaseAssignmentResult:
    # Verify engagement exists
    if store.get(engagement_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Engagement not found")
    count = store.assign_cases(engagement_id, body.case_ids)
    return CaseAssignmentResult(count=count)


@router.delete("/{engagement_id}/cases")
def remove_cases(
    engagement_id: str,
    body: CaseAssignment,
    user: dict[str, str] = Depends(require_role("manager")),
    store: EngagementStore = Depends(get_engagement_store),
) -> CaseAssignmentResult:
    if store.get(engagement_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Engagement not found")
    count = store.remove_cases(engagement_id, body.case_ids)
    return CaseAssignmentResult(count=count)


@router.get("/{engagement_id}/summary")
def get_engagement_summary(
    engagement_id: str,
    user: dict[str, str] = Depends(require_role("analyst")),
    store: EngagementStore = Depends(get_engagement_store),
) -> EngagementSummaryResponse:
    summary = store.get_summary(engagement_id)
    if summary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Engagement not found")
    return EngagementSummaryResponse(**summary)


@router.get("/{engagement_id}/analytics")
def get_engagement_analytics(
    engagement_id: str,
    user: dict[str, str] = Depends(require_role("analyst")),
    store: EngagementStore = Depends(get_engagement_store),
) -> EngagementExtendedSummaryResponse:
    """Extended analytics for an engagement including classification distribution."""
    summary = store.get_extended_summary(engagement_id)
    if summary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Engagement not found")
    return EngagementExtendedSummaryResponse(**summary)


@router.get("/{engagement_id}/leaderboard")
def get_engagement_leaderboard(
    engagement_id: str,
    user: dict[str, str] = Depends(require_role("analyst")),
    store: EngagementStore = Depends(get_engagement_store),
) -> LeaderboardResponse:
    """Ranked leaderboard of analysts within an engagement."""
    settings = get_settings()
    weights = settings.analytics.leaderboard_weights
    entries = store.get_leaderboard(engagement_id, weights=weights)
    if entries is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Engagement not found")
    return LeaderboardResponse(
        engagement_id=engagement_id,
        entries=[LeaderboardEntry(**e) for e in entries],
        total_analysts=len(entries),
    )


@router.get("/{engagement_id}/export")
def export_engagement(
    engagement_id: str,
    fmt: str = Query("csv", description="Export format: csv or json"),
    user: dict[str, str] = Depends(require_role("manager")),
    store: EngagementStore = Depends(get_engagement_store),
) -> StreamingResponse:
    """Export engagement analytics and leaderboard as CSV or JSON."""
    summary = store.get_extended_summary(engagement_id)
    if summary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Engagement not found")

    settings = get_settings()
    weights = settings.analytics.leaderboard_weights
    entries = store.get_leaderboard(engagement_id, weights=weights) or []

    eng_name = summary.get("name", engagement_id).replace(" ", "_").lower()

    if fmt == "json":
        import json

        payload = {
            "summary": {
                "engagement_id": summary["engagement_id"],
                "name": summary["name"],
                "status": summary["status"],
                "case_count": summary["case_count"],
                "cases_reviewed": summary["cases_reviewed"],
                "review_completion_pct": summary["review_completion_pct"],
                "analyst_count": summary.get("analyst_count", 0),
                "classification_distribution": summary.get("classification_distribution", {}),
                "avg_review_time_hours": summary.get("avg_review_time_hours"),
            },
            "leaderboard": entries,
        }
        content = json.dumps(payload, indent=2, default=str)
        return StreamingResponse(
            io.StringIO(content),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="engagement_{eng_name}.json"'},
        )

    # CSV export
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Rank",
            "Analyst",
            "Cases Reviewed",
            "Avg Review Time (s)",
            "Classification Accuracy",
            "Risk Score MAE",
            "Actions Logged",
            "Composite Score",
        ]
    )
    for entry in entries:
        writer.writerow(
            [
                entry["rank"],
                entry["analyst_email"],
                entry["cases_reviewed"],
                entry.get("avg_review_time_seconds", ""),
                entry.get("classification_accuracy", ""),
                entry.get("risk_score_mae", ""),
                entry.get("actions_logged", 0),
                entry.get("composite_score", ""),
            ]
        )
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="engagement_{eng_name}.csv"'},
    )


# ---------------------------------------------------------------------------
# Phase 4 — Cross-Engagement Intelligence
# ---------------------------------------------------------------------------


class CrossEngagementKPI(CamelModel):
    engagement_id: str
    engagement_name: str | None = None
    engagement_status: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    total_cases: int = 0
    proactive_cases: int = 0
    reactive_cases: int = 0
    total_loss: float = 0.0
    new_indicators: int = 0
    new_entities: int = 0
    cases_actioned: int = 0
    period_start: datetime | None = None


class SemesterTrendRow(CamelModel):
    engagement_id: str
    engagement_name: str | None = None
    period_type: str
    period_start: datetime | None = None
    total_cases: int = 0
    proactive_cases: int = 0
    reactive_cases: int = 0
    total_loss: float = 0.0
    new_indicators: int = 0
    new_entities: int = 0
    cases_actioned: int = 0


class UniversityComparison(CamelModel):
    university: str
    engagement_count: int = 0
    total_cases: int = 0
    total_loss: float = 0.0
    total_indicators: int = 0
    total_entities: int = 0
    cases_actioned: int = 0
    engagements: list[dict[str, Any]] = []


@router.get("/compare/kpis")
def compare_engagement_kpis(
    user: dict[str, str] = Depends(require_role("manager")),
) -> list[CrossEngagementKPI]:
    """Cross-engagement KPI comparison — latest weekly snapshot per engagement."""
    from i4g.worker.jobs.bq_export import get_cross_engagement_kpis

    sf = build_sql_session_factory()
    with sf() as session:
        rows = get_cross_engagement_kpis(session)
    return [CrossEngagementKPI(**r) for r in rows]


@router.get("/compare/trends")
def compare_engagement_trends(
    engagement_ids: str | None = Query(None, description="Comma-separated engagement IDs"),
    user: dict[str, str] = Depends(require_role("manager")),
) -> list[SemesterTrendRow]:
    """Semester-over-semester weekly KPI time series per engagement."""
    from i4g.worker.jobs.bq_export import get_semester_trends

    ids = [eid.strip() for eid in engagement_ids.split(",") if eid.strip()] if engagement_ids else None
    sf = build_sql_session_factory()
    with sf() as session:
        rows = get_semester_trends(session, engagement_ids=ids)
    return [SemesterTrendRow(**r) for r in rows]


@router.get("/compare/universities")
def compare_universities(
    user: dict[str, str] = Depends(require_role("manager")),
) -> list[UniversityComparison]:
    """Aggregate KPIs by university for partnership comparison reports."""
    from i4g.worker.jobs.bq_export import get_university_comparison

    sf = build_sql_session_factory()
    with sf() as session:
        rows = get_university_comparison(session)
    return [UniversityComparison(**r) for r in rows]
