"""Engagement scoping middleware.

Reads the ``X-Engagement-Id`` request header and stores it on
``request.state.engagement_id`` for downstream route handlers.

When the header is absent, ``engagement_id`` is set to ``None``
(meaning "All Engagements" mode).
"""

from __future__ import annotations

import logging
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

HEADER_NAME = "X-Engagement-Id"


class EngagementScopeMiddleware(BaseHTTPMiddleware):
    """Extract and validate the optional ``X-Engagement-Id`` header."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        raw = request.headers.get(HEADER_NAME)
        if raw:
            # Validate UUID format to prevent injection
            try:
                uuid.UUID(raw)
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={"detail": f"Invalid {HEADER_NAME}: must be a valid UUID"},
                )
            request.state.engagement_id = raw
        else:
            request.state.engagement_id = None

        return await call_next(request)
