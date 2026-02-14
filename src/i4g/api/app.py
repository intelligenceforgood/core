"""FastAPI app factory for i4g Analyst Review API."""

import time

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from i4g.api.response_models import TaskStatusResponse, TaskUpdateResponse

from i4g.api.account_list import router as account_list_router
from i4g.api.accounts import router as accounts_router
from i4g.api.analytics import router as analytics_router
from i4g.api.auth import require_role, require_token
from i4g.api.cases import router as cases_router
from i4g.api.campaigns import router as campaigns_router
from i4g.api.dashboard import router as dashboard_router

from i4g.api.discovery import router as discovery_router
from i4g.api.evidence import router as evidence_router
from i4g.api.intake import router as intake_router
from i4g.api.reports import router as reports_router
from i4g.api.review import router as review_router
from i4g.api.taxonomy import router as taxonomy_router
from i4g.api.tokenization import router as tokenization_router
from i4g.settings import get_settings
from i4g.task_status_store import TASK_STATUS

# ----------------------------------------
# Task Status API (Step 2 of M6.3)
# ----------------------------------------

task_router = APIRouter(prefix="/tasks", tags=["tasks"], dependencies=[Depends(require_token)])

@task_router.get("/{task_id}", response_model=TaskStatusResponse)
def get_task_status(task_id: str) -> dict[str, str]:
    """Retrieve the current status of a background task.

    This endpoint is used by the analyst console or external clients to monitor report
    generation, ingestion, or review actions.

    Args:
        task_id: The unique identifier of the task.

    Returns:
        A dictionary containing the task ID, status, and any associated message.
    """
    if task_id not in TASK_STATUS:
        return {"task_id": task_id, "status": "unknown", "message": "Task not found"}

    return {"task_id": task_id, **TASK_STATUS[task_id]}


@task_router.post("/{task_id}/update", response_model=TaskUpdateResponse)
def update_task_status(
    task_id: str,
    payload: dict[str, str],
    user: dict = Depends(require_role("admin")),
) -> dict[str, str | bool]:
    """Update or register a task status entry.

    This simulates what a background worker would do.

    Args:
        task_id: The unique identifier of the task.
        payload: A dictionary containing status updates (e.g., status, message).

    Returns:
        A dictionary confirming the update.
    """
    TASK_STATUS[task_id] = payload
    return {"task_id": task_id, "updated": True}


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        Configured FastAPI instance.
    """
    app = FastAPI(title="i4g Analyst Review API", version="0.1")

    settings = get_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Taxonomy-Version"],
    )

    app.include_router(review_router, prefix="/reviews", tags=["reviews"])
    app.include_router(account_list_router)
    app.include_router(accounts_router)
    app.include_router(analytics_router)
    app.include_router(cases_router)
    app.include_router(campaigns_router)
    app.include_router(dashboard_router)

    app.include_router(discovery_router)
    app.include_router(evidence_router)
    app.include_router(intake_router)
    app.include_router(reports_router)
    app.include_router(taxonomy_router)
    app.include_router(tokenization_router)
    app.include_router(task_router)

    # Serve artifacts
    artifacts_dir = Path(settings.data_dir) / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/artifacts", StaticFiles(directory=str(artifacts_dir)), name="artifacts")

    return app


# For uvicorn, expose `app` at module level
app = create_app()
SETTINGS = get_settings()

# ----------------------------------------
# Simple Rate Limiting and Queue Control
# ----------------------------------------

# In-memory request log (in production, replace with Redis or PostgreSQL table)
REQUEST_LOG = {}
MAX_REQUESTS_PER_MINUTE = SETTINGS.api.rate_limit_per_minute


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """
    Basic per-IP rate limiter. Blocks clients that exceed
    MAX_REQUESTS_PER_MINUTE requests in a rolling 60s window.
    """
    if MAX_REQUESTS_PER_MINUTE <= 0:
        return await call_next(request)
    client_ip = request.headers.get("x-forwarded-for") or (request.client.host if request.client else "unknown")
    now = time.time()
    window_start = now - 60

    # Get or create the list of timestamps for the client IP
    timestamps = REQUEST_LOG.setdefault(client_ip, [])

    # Remove old timestamps in-place
    timestamps[:] = [t for t in timestamps if t > window_start]

    # Check if the rate limit is exceeded
    if len(timestamps) >= MAX_REQUESTS_PER_MINUTE:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")

    # Log the new request timestamp
    timestamps.append(now)

    response = await call_next(request)
    return response


# Report generation is handled by the worker task pipeline
# (see ``i4g.worker.tasks.generate_report_for_case`` and reports router).
# The legacy ``/reports/generate`` stub has been removed (E29).

# Expose REQUEST_LOG for testing purposes
__all__ = ["app", "REQUEST_LOG"]
