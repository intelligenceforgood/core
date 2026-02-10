"""Review detail sub-router.

Endpoints for retrieving individual reviews, case-based lookups,
and action history. Mounted by the main ``review.py`` orchestrator.
"""

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query

from i4g.api.auth import require_token
from i4g.api.response_models import ActionHistoryResponse, CaseReviewsResponse
from i4g.api.review_deps import get_store
from i4g.store.review_store import ReviewStore

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/case/{case_id}", summary="List review entries for a given case", response_model=CaseReviewsResponse)
def reviews_by_case(
    case_id: str,
    limit: int = Query(5, ge=1, le=50),
    store: ReviewStore = Depends(get_store),
    user=Depends(require_token),
):
    """Return review queue entries associated with a specific case."""
    reviews = store.get_reviews_by_case(case_id=case_id, limit=limit)
    return {"case_id": case_id, "reviews": reviews, "count": len(reviews)}


@router.get("/{review_id}", summary="Get a review item")
def get_review(review_id: str, store: ReviewStore = Depends(get_store), user=Depends(require_token)):
    """Get full review item by ID."""
    item = store.get_review(review_id)
    if not item:
        raise HTTPException(status_code=404, detail="Review not found")
    return item


@router.get("/{review_id}/actions", summary="Get review action history", response_model=ActionHistoryResponse)
def actions(review_id: str, store: ReviewStore = Depends(get_store), user=Depends(require_token)):
    """Return audit trail for a review."""
    action_list = store.get_actions(review_id)
    return {"review_id": review_id, "actions": action_list}
