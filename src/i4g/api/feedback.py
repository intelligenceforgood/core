"""FastAPI router for feedback submission."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from i4g.api.auth import require_token
from i4g.services.feedback import FeedbackPayload, FeedbackService
from i4g.settings import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/feedback", tags=["feedback"])


class FeedbackRequest(BaseModel):
    """Incoming feedback submission from the analyst console.

    Mirrors FeedbackPayload but allows the API layer to inject submitter from
    the auth context.
    """

    feedback_id: str
    feedback_type: str
    priority: str = "P2-Medium"
    subject: str
    description: str
    page_url: str = ""
    user_agent: str = ""


class FeedbackResponse(BaseModel):
    """Response after submitting feedback."""

    success: bool
    message: str


def _get_service() -> FeedbackService:
    """Build the appropriate feedback service based on settings.

    When ``I4G_ENV=local``, always returns :class:`LoggingFeedbackService` so
    that local ADC credentials (which lack the Sheets OAuth scope) are never
    required during development.

    Returns:
        A FeedbackService implementation.
    """
    settings = get_settings()
    if not settings.feedback.enabled:
        raise HTTPException(status_code=503, detail="Feedback submission is disabled")

    # Local dev: log to stdout; never require Sheets API credentials.
    if settings.env == "local":
        from i4g.services.feedback import LoggingFeedbackService

        return LoggingFeedbackService()

    sheet_id = settings.feedback.sheet_id
    if not sheet_id:
        from i4g.services.feedback import LoggingFeedbackService

        logger.warning(
            "feedback.sheet_id not configured — falling back to LoggingFeedbackService (env=%s)", settings.env
        )
        return LoggingFeedbackService()

    logger.debug("Using GoogleSheetsFeedbackService (sheet_id=%s env=%s)", sheet_id, settings.env)
    from i4g.services.feedback import GoogleSheetsFeedbackService

    return GoogleSheetsFeedbackService(sheet_id=sheet_id)


@router.post("", response_model=FeedbackResponse)
def submit_feedback(
    body: FeedbackRequest,
    user: dict[str, Any] = Depends(require_token),
) -> FeedbackResponse:
    """Submit inline feedback from the analyst console.

    Auto-fills the submitter from the authenticated user context.

    Args:
        body: The feedback form data.
        user: Injected from the auth middleware.

    Returns:
        Success or failure response.
    """
    submitter = user.get("username") or user.get("email") or user.get("sub") or "unknown"
    payload = FeedbackPayload(
        feedback_id=body.feedback_id,
        feedback_type=body.feedback_type,
        priority=body.priority,
        subject=body.subject,
        description=body.description,
        submitter=submitter,
        page_url=body.page_url,
        user_agent=body.user_agent,
    )

    service = _get_service()
    ok = service.submit(payload)

    if ok:
        return FeedbackResponse(success=True, message="Feedback submitted — thank you!")
    raise HTTPException(status_code=500, detail="Failed to save feedback. Please try again.")
