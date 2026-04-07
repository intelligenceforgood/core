"""Engagement CRUD and case-assignment API router."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from i4g.api.auth import require_role, require_token
from i4g.api.camel import CamelModel
from i4g.services.factories import build_engagement_store
from i4g.store.engagement_store import EngagementStore

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
