"""FastAPI app factory for i4g Analyst Review API."""

import logging
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from i4g.api.accounts import router as accounts_router
from i4g.api.analytics import router as analytics_router
from i4g.api.auth import require_token
from i4g.api.campaigns import router as campaigns_router
from i4g.api.cases import router as cases_router
from i4g.api.dashboard import router as dashboard_router
from i4g.api.discovery import router as discovery_router
from i4g.api.evidence import router as evidence_router
from i4g.api.exports import router as exports_router
from i4g.api.feedback import router as feedback_router
from i4g.api.impact import router as impact_router
from i4g.api.intake import router as intake_router
from i4g.api.intelligence import router as intelligence_router
from i4g.api.investigations import router as investigations_router
from i4g.api.partner_feed import router as partner_feed_router
from i4g.api.reports import router as reports_router
from i4g.api.response_models import TaskStatusResponse, TaskUpdateResponse
from i4g.api.review import router as review_router
from i4g.api.ssi_events import router as ssi_events_router
from i4g.api.ssi_evidence import router as ssi_evidence_router
from i4g.api.ssi_investigations import router as ssi_investigations_router
from i4g.api.ssi_playbooks import router as ssi_playbooks_router
from i4g.api.ssi_wallets import router as ssi_wallets_router
from i4g.api.taxonomy import router as taxonomy_router
from i4g.settings import get_settings
from i4g.task_status_store import TASK_STATUS

logger = logging.getLogger(__name__)

# ----------------------------------------
# Task Status API (Step 2 of M6.3)
# ----------------------------------------

task_router = APIRouter(prefix="/tasks", tags=["tasks"], dependencies=[Depends(require_token)])

# Scans that have been "running" longer than this with no DB update are
# considered orphaned (e.g. SSI process killed mid-investigation).
_STALE_RUNNING_THRESHOLD = timedelta(hours=2)


def _stale_running_scan(scan: dict[str, Any]) -> bool:
    """Return True when a 'running' scan has not been updated recently.

    Uses ``updated_at`` (kept current by TaskStatusReporter) with a
    fallback to ``started_at``.  Returns False when neither column is set
    so that scans without timestamps are not incorrectly failed.

    Args:
        scan: Row dict from ``SsiStore.get_scan()``.

    Returns:
        True if the scan is older than ``_STALE_RUNNING_THRESHOLD``.
    """
    ts = scan.get("updated_at") or scan.get("started_at")
    if not ts:
        return False
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts)
        except ValueError:
            return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return datetime.now(UTC) - ts > _STALE_RUNNING_THRESHOLD


@task_router.get("/{task_id}", response_model=TaskStatusResponse, response_model_exclude_none=True)
def get_task_status(task_id: str) -> dict[str, Any]:
    """Retrieve the current status of a background task.

    This endpoint is used by the analyst console or external clients to monitor report
    generation, ingestion, or review actions.

    Args:
        task_id: The unique identifier of the task.

    Returns:
        A dictionary containing the task ID, status, and any associated message.
    """
    if task_id not in TASK_STATUS:
        # DB fallback for SSI investigations: scan_id == task_id, so a direct
        # lookup works across Cloud Run instances that don't share in-memory
        # TASK_STATUS.  Gracefully skip non-SSI task_ids (store returns None).
        try:
            from i4g.services.factories import build_ssi_store

            _store = build_ssi_store()
            _scan = _store.get_scan(task_id)
            if _scan:
                _status = str(_scan.get("status", "running"))
                if _status == "running" and _stale_running_scan(_scan):
                    _url = str(_scan.get("url", ""))
                    _err = "Investigation was interrupted (service restarted while it was running)."
                    try:
                        _store.update_scan(task_id, status="failed", error_message=_err)
                    except Exception as _ue:
                        logging.getLogger(__name__).warning("Could not mark stale scan %s as failed: %s", task_id, _ue)
                    _status = "failed"
                    _scan = {**_scan, "status": "failed", "error_message": _err}
                _url = str(_scan.get("url", ""))
                _msg = f"Investigation {_status}: {_url}"
                if _status == "failed" and _scan.get("error_message"):
                    _msg = str(_scan["error_message"])
                return {
                    "task_id": task_id,
                    "status": _status,
                    "message": _msg,
                    "investigation_id": task_id,
                    "risk_score": float(_scan["risk_score"]) if _scan.get("risk_score") is not None else None,
                    "case_id": _scan.get("case_id"),
                    "duration_seconds": (
                        float(_scan["duration_seconds"]) if _scan.get("duration_seconds") is not None else None
                    ),
                }
        except Exception as _e:
            logging.getLogger(__name__).debug("SSI DB fallback failed for task %s: %s", task_id, _e)
        return {"task_id": task_id, "status": "unknown", "message": "Task not found"}

    task = TASK_STATUS[task_id]
    scan_id = task.get("scan_id")

    if scan_id:
        try:
            from i4g.services.factories import build_ssi_store

            store = build_ssi_store()
            scan = store.get_scan(scan_id)
            if scan:
                # Update task with latest from DB; auto-fail orphaned running scans.
                status = scan["status"]
                if status == "running" and _stale_running_scan(scan):
                    err_msg = "Investigation was interrupted (service restarted while it was running)."
                    try:
                        store.update_scan(scan_id, status="failed", error_message=err_msg)
                    except Exception as _ue:
                        logging.getLogger(__name__).warning("Could not mark stale scan %s as failed: %s", scan_id, _ue)
                    status = "failed"
                    scan = {**scan, "status": "failed", "error_message": err_msg}
                message = f"Investigation {status}: {task.get('url', 'unknown URL')}"
                if status == "failed" and scan.get("error_message"):
                    message = scan["error_message"]

                return {
                    "task_id": task_id,
                    **task,
                    "status": status,
                    "message": message,
                    "investigation_id": scan_id,
                    "risk_score": float(scan["risk_score"]) if scan.get("risk_score") is not None else None,
                    "case_id": scan.get("case_id"),
                    "duration_seconds": (
                        float(scan["duration_seconds"]) if scan.get("duration_seconds") is not None else None
                    ),
                }
        except Exception as e:
            logging.getLogger(__name__).warning("Failed to look up SSI scan status for %s: %s", scan_id, e)

    # Ensure investigation_id is always populated when scan_id is present,
    # even if the DB lookup above failed.  Without this, TaskStatusResponse
    # drops the raw scan_id key and serializes investigationId as null.
    if scan_id and "investigation_id" not in task:
        task = {**task, "investigation_id": scan_id}

    return {"task_id": task_id, **task}


@task_router.post("/{task_id}/update", response_model=TaskUpdateResponse)
def update_task_status(
    task_id: str,
    payload: dict[str, Any],
    user: dict = Depends(require_token),
) -> dict[str, str | bool]:
    """Update or register a task status entry.

    Called by background workers (Cloud Run Jobs, SSI TaskStatusReporter)
    to report progress.  Accepts any authenticated token (API key or IAP).

    Args:
        task_id: The unique identifier of the task.
        payload: A dictionary containing status updates (e.g., status, message).

    Returns:
        A dictionary confirming the update.
    """
    # Merge into existing task data so that fields set at trigger time
    # (e.g. scan_id, url) are preserved across incremental updates.
    existing = TASK_STATUS.get(task_id, {})
    existing.update(payload)
    TASK_STATUS[task_id] = existing
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
    app.include_router(accounts_router)
    app.include_router(analytics_router)
    app.include_router(cases_router)
    app.include_router(campaigns_router)
    app.include_router(dashboard_router)

    app.include_router(discovery_router)
    app.include_router(evidence_router)
    app.include_router(exports_router)
    app.include_router(feedback_router)
    app.include_router(impact_router)
    app.include_router(intake_router)
    app.include_router(intelligence_router)
    # SSI routers registered before investigations_router so static paths
    # (/history, /active, /wallets) resolve before the catch-all {task_id}.
    # Wallets + evidence must come before ssi_investigations because the
    # ssi_investigations router has a /{scan_id} catch-all that would
    # otherwise swallow /wallets, /*/wallets.csv, etc.
    # Playbooks have their own prefix (/playbooks/ssi) — no ordering issue.
    app.include_router(ssi_playbooks_router)
    app.include_router(ssi_wallets_router)
    app.include_router(ssi_evidence_router)
    app.include_router(ssi_events_router)
    app.include_router(ssi_investigations_router)
    app.include_router(investigations_router)
    app.include_router(reports_router)
    app.include_router(taxonomy_router)
    app.include_router(partner_feed_router)
    app.include_router(task_router)

    # Serve artifacts
    artifacts_dir = Path(settings.data_dir) / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/artifacts", StaticFiles(directory=str(artifacts_dir)), name="artifacts")

    # Warn at startup if SSI service URL is missing in non-local environments.
    # Investigations will fail at request time without this, so surface it early.
    if settings.env.lower() != "local" and not settings.ssi.service_url:
        logger.warning(
            "I4G_SSI__SERVICE_URL is not set (env=%s). "
            "POST /investigations/ssi will fail until the SSI Cloud Run Service URL is configured.",
            settings.env,
        )

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
