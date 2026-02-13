"""Review queue and action sub-router.

Endpoints for enqueueing, claiming, annotating, and deciding on reviews.
Mounted by the main ``review.py`` orchestrator.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
from i4g.settings import PROJECT_ROOT
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
    priority: str | None = "medium"
    # Optional preview fields for the UI
    text: str | None = None
    classification: ClassificationResult | None = None
    tags: list[str] | None = None
    entities: dict[str, Any] | None = None


class DecisionRequest(BaseModel):
    decision: str  # accepted | rejected | needs_more_info
    notes: str | None = None
    auto_generate_report: bool | None = False


class AnnotateRequest(BaseModel):
    annotations: dict[str, Any]
    notes: str | None = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/", summary="Enqueue a case for review", response_model=EnqueueResponse)
def enqueue_case(
    payload: EnqueueRequest,
    user: dict[str, Any] = Depends(require_token),
    store: ReviewStore = Depends(get_store),
) -> dict[str, str]:
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
) -> dict[str, Any]:
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
    """Submit corrections or validations for automated classification.

    This endpoint:
    1. Logs the feedback as an audit action.
    2. Applies the corrected classification to the case (updates cases + review_queue).
    3. Writes a golden dataset candidate for curator review.
    """
    actor = user.get("username", "unknown")

    # 1. Log feedback as audit trail
    store.log_action(
        review_id,
        actor=actor,
        action="analyst_feedback",
        payload=payload.model_dump(),
    )

    # 2. Apply corrected classification to the case
    corrected_dict = payload.corrected_classification.model_dump()
    case_id = store.apply_feedback_classification(review_id, corrected_dict)

    if not case_id:
        raise HTTPException(status_code=404, detail=f"Review {review_id} not found")

    # 3. Write golden dataset candidate (F17)
    _write_golden_candidate(
        case_id=case_id,
        review_id=review_id,
        actor=actor,
        original=payload.original_classification.model_dump() if payload.original_classification else None,
        corrected=corrected_dict,
        notes=payload.notes,
        input_text=store.get_case_text(case_id),
    )

    logger.info(
        "Feedback applied: review_id=%s case_id=%s actor=%s",
        review_id,
        case_id,
        actor,
    )
    return {"review_id": review_id, "feedback_recorded": True}


def _write_golden_candidate(
    *,
    case_id: str,
    review_id: str,
    actor: str,
    original: dict[str, Any] | None,
    corrected: dict[str, Any],
    notes: str | None,
    input_text: str | None,
) -> None:
    """Append a feedback correction to the golden dataset candidates file.

    Candidates require manual curator review before promotion to the
    official golden_examples.json used for few-shot prompting.
    """
    candidates_path = PROJECT_ROOT / "src" / "i4g" / "taxonomy" / "golden_candidates.json"

    candidate = {
        "case_id": case_id,
        "review_id": review_id,
        "actor": actor,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "notes": notes,
        "input": input_text or "",
        "original_classification": original,
        "corrected_classification": corrected,
        "status": "pending_review",
    }

    # Load existing candidates
    existing: list[dict[str, Any]] = []
    if candidates_path.exists():
        try:
            existing = json.loads(candidates_path.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to read golden candidates file; starting fresh.")

    existing.append(candidate)

    try:
        candidates_path.write_text(json.dumps(existing, indent=2, default=str) + "\n")
    except OSError:
        logger.error("Failed to write golden candidate for case %s", case_id)


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
