"""Review queue and action sub-router.

Endpoints for enqueueing, claiming, annotating, and deciding on reviews.
Mounted by the main ``review.py`` orchestrator.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel

from i4g.api.auth import require_token
from i4g.api.response_models import (
    AnnotateResponse,
    ClaimResponse,
    DecisionResponse,
    EnqueueResponse,
    FeedbackResponse,
    ItemListResponse,
)
from i4g.api.review_deps import get_store
from i4g.store.review_store import ReviewStore
from i4g.taxonomy.models import AnalystFeedbackRequest, ClassificationResult
from i4g.worker.tasks import generate_report_for_case

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class EnqueueRequest(BaseModel):
    case_id: str
    priority: Optional[str] = "medium"
    # Optional preview fields for the UI
    text: Optional[str] = None
    classification: Optional[ClassificationResult] = None
    tags: Optional[List[str]] = None
    entities: Optional[Dict[str, Any]] = None


class DecisionRequest(BaseModel):
    decision: str  # accepted | rejected | needs_more_info
    notes: Optional[str] = None
    auto_generate_report: Optional[bool] = False


class AnnotateRequest(BaseModel):
    annotations: Dict[str, Any]
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/", summary="Enqueue a case for review", response_model=EnqueueResponse)
def enqueue_case(
    payload: EnqueueRequest,
    user: Dict[str, Any] = Depends(require_token),
    store: ReviewStore = Depends(get_store),
) -> Dict[str, str]:
    """Add a case to the review queue.

    Args:
        payload: The request payload containing case ID and priority.
        user: The authenticated user (injected dependency).
        store: The review store instance (injected dependency).

    Returns:
        A dictionary containing the new review ID and the case ID.
    """
    logger.info("enqueue_case: case_id=%s priority=%s user=%s", payload.case_id, payload.priority, user.get("username"))
    review_id = store.enqueue_case(
        case_id=payload.case_id,
        priority=payload.priority,
        classification_result=payload.classification.model_dump() if payload.classification else None,
        tags=payload.tags,
    )
    store.log_action(
        review_id,
        actor=user["username"],
        action="enqueued",
        payload={"text": payload.text or ""},
    )
    return {"review_id": review_id, "case_id": payload.case_id}


@router.get("/queue", summary="List queued cases", response_model=ItemListResponse)
def list_queue(
    status: str = Query("new"),
    limit: int = Query(25),
    store: ReviewStore = Depends(get_store),
    user=Depends(require_token),
) -> Dict[str, Any]:
    """List queued cases by status.

    Args:
        status: The status to filter by (default: "new").
        limit: The maximum number of items to return.
        store: The review store instance.

    Returns:
        A dictionary containing the list of items and the count.
    """
    items = store.get_queue(status=status, limit=limit)
    return {"items": items, "count": len(items)}


@router.post("/{review_id}/claim", summary="Claim a review", response_model=ClaimResponse)
def claim_review(review_id: str, user=Depends(require_token), store: ReviewStore = Depends(get_store)):
    """Assign current user to the review and log action."""
    logger.info("claim_review: review_id=%s user=%s", review_id, user.get("username"))
    store.update_status(review_id, status="in_review", notes=f"claimed by {user['username']}")
    store.log_action(review_id, actor=user["username"], action="claimed")
    return {"review_id": review_id, "status": "in_review"}


@router.post("/{review_id}/annotate", summary="Annotate a review item", response_model=AnnotateResponse)
def annotate_review(
    review_id: str,
    payload: AnnotateRequest,
    user=Depends(require_token),
    store: ReviewStore = Depends(get_store),
):
    """Attach annotations and notes to a review; logs action."""
    store.log_action(
        review_id,
        actor=user["username"],
        action="annotate",
        payload={"annotations": payload.annotations, "notes": payload.notes},
    )
    return {"review_id": review_id, "annotated": True}


@router.post("/{review_id}/feedback", summary="Submit analyst feedback on classification", response_model=FeedbackResponse)
def submit_feedback(
    review_id: str,
    payload: AnalystFeedbackRequest,
    user=Depends(require_token),
    store: ReviewStore = Depends(get_store),
):
    """Submit corrections or validations for automated classification."""
    store.log_action(
        review_id,
        actor=user["username"],
        action="analyst_feedback",
        payload=payload.model_dump(),
    )
    return {"review_id": review_id, "feedback_recorded": True}


@router.post("/{review_id}/decision", summary="Make a decision on a review", response_model=DecisionResponse)
def decision(
    review_id: str,
    payload: DecisionRequest,
    background_tasks: BackgroundTasks,
    user=Depends(require_token),
    store: ReviewStore = Depends(get_store),
):
    """Record a decision (accepted/rejected/needs_more_info).

    If decision is 'accepted' and auto_generate_report is True,
    schedule background report generation.
    """
    if payload.decision not in {"accepted", "rejected", "needs_more_info", "in_review"}:
        raise HTTPException(status_code=400, detail="Invalid decision")

    logger.info(
        "decision: review_id=%s decision=%s user=%s",
        review_id,
        payload.decision,
        user.get("username"),
    )
    store.update_status(review_id, status=payload.decision, notes=payload.notes)
    store.log_action(
        review_id,
        actor=user["username"],
        action="decision",
        payload={"decision": payload.decision, "notes": payload.notes},
    )

    if payload.decision == "accepted" and payload.auto_generate_report:
        background_tasks.add_task(generate_report_for_case, review_id, store)

    return {"review_id": review_id, "status": payload.decision}
