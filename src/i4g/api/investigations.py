"""SSI investigation trigger endpoints for the analyst console.

Provides ``POST /investigations/ssi`` to launch an SSI Cloud Run Job
that investigates a suspicious URL.  The endpoint returns a task ID
that the caller polls via ``GET /tasks/{task_id}`` for progress.

**Phase 3 (3.1, 3.2):** Core API triggers SSI investigations and
tracks their progress via the shared TASK_STATUS system.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from i4g.api.auth import require_role, require_token
from i4g.api.camel import CamelModel
from i4g.settings import get_settings
from i4g.task_status_store import TASK_STATUS

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/investigations",
    tags=["investigations"],
    dependencies=[Depends(require_token)],
)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class SsiInvestigationRequest(CamelModel):
    """Payload for triggering an SSI investigation."""

    url: str = Field(..., description="The suspicious URL to investigate.")
    scan_type: Literal["passive", "active", "full"] = Field(
        default="full",
        description="Investigation mode: passive (OSINT only), active (agent only), or full.",
    )
    push_to_core: bool = Field(
        default=True,
        description="Push investigation results to a core case record.",
    )
    trigger_dossier: bool = Field(
        default=False,
        description="Queue dossier generation after investigation completes.",
    )
    dataset: str = Field(
        default="ssi",
        description="Dataset label for the case created in core.",
    )


class SsiInvestigationResponse(CamelModel):
    """Response after triggering an SSI investigation."""

    task_id: str
    status: str
    message: str
    job_name: str | None = None


# ---------------------------------------------------------------------------
# Cloud Run Job trigger
# ---------------------------------------------------------------------------


def _trigger_cloud_run_job(
    *,
    project: str,
    region: str,
    job_name: str,
    env_overrides: dict[str, str],
    service_account: str | None = None,
) -> str:
    """Trigger a Cloud Run Job execution via the REST API.

    Uses Application Default Credentials (ADC).  On Cloud Run the attached
    service account already has ``roles/run.invoker``; locally, impersonate
    via ``gcloud auth application-default login``.

    Args:
        project: GCP project ID.
        region: GCP region.
        job_name: Cloud Run Job name (e.g. ``ssi-investigate``).
        env_overrides: Environment variable overrides for the container.
        service_account: Optional SA to impersonate for the API call.

    Returns:
        The Cloud Run operation name for the execution.

    Raises:
        RuntimeError: When the API call fails.
    """
    try:
        import google.auth
        import google.auth.transport.requests
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError(
            "google-auth and google-api-python-client are required to trigger Cloud Run Jobs"
        ) from exc

    creds, _ = google.auth.default()

    if service_account:
        import google.auth.impersonated_credentials

        creds = google.auth.impersonated_credentials.Credentials(
            source_credentials=creds,
            target_principal=service_account,
            target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        request = google.auth.transport.requests.Request()
        creds.refresh(request)

    service = build("run", "v2", credentials=creds, cache_discovery=False)
    parent = f"projects/{project}/locations/{region}/jobs/{job_name}"

    overrides: dict[str, Any] = {}
    if env_overrides:
        container_override: dict[str, Any] = {
            "env": [{"name": k, "value": v} for k, v in env_overrides.items()],
        }
        overrides["containerOverrides"] = [container_override]

    logger.info("Triggering Cloud Run Job %s with overrides: %s", parent, list(env_overrides.keys()))

    request = service.projects().locations().jobs().run(
        name=parent, body={"overrides": overrides}
    )
    operation = request.execute()
    op_name = operation.get("name", "")
    logger.info("Cloud Run Job started: %s", op_name)
    return op_name


def _trigger_local_investigation(
    task_id: str,
    url: str,
    scan_type: str,
    push_to_core: bool,
    trigger_dossier: bool,
    dataset: str,
) -> None:
    """Run an SSI investigation locally via subprocess for local-dev.

    Fires ``ssi job investigate`` in a background subprocess so the API
    returns immediately.  Task status updates flow through the shared
    ``TASK_STATUS`` dict (in-memory — same process group in local dev).

    Args:
        task_id: Task identifier for status tracking.
        url: URL to investigate.
        scan_type: Investigation mode.
        push_to_core: Whether to push results to core.
        trigger_dossier: Whether to trigger dossier generation.
        dataset: Dataset label.
    """
    import subprocess
    import sys

    env_vars = {
        "SSI_JOB__URL": url,
        "SSI_JOB__SCAN_TYPE": scan_type,
        "SSI_JOB__PUSH_TO_CORE": str(push_to_core).lower(),
        "SSI_JOB__TRIGGER_DOSSIER": str(trigger_dossier).lower(),
        "SSI_JOB__DATASET": dataset,
        "I4G_TASK_ID": task_id,
    }

    import os

    full_env = {**os.environ, **env_vars}

    # Attempt to run ssi CLI in a subprocess
    try:
        subprocess.Popen(
            [sys.executable, "-m", "ssi.worker.jobs"],
            env=full_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info("Launched local SSI investigation subprocess for task %s", task_id)
    except FileNotFoundError:
        TASK_STATUS[task_id] = {
            "status": "failed",
            "message": "SSI package not available locally. Install ssi to use local investigation mode.",
        }
        logger.warning("SSI not available locally — cannot run investigation")


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/ssi",
    summary="Trigger an SSI investigation",
    status_code=202,
    response_model=SsiInvestigationResponse,
)
def trigger_ssi_investigation(
    payload: SsiInvestigationRequest,
    user: dict[str, str] = Depends(require_role("analyst")),
) -> dict[str, Any]:
    """Trigger an SSI scam-site investigation via Cloud Run Job.

    Creates a task entry in the TASK_STATUS store and triggers the SSI
    Cloud Run Job (or subprocess in local mode).  The client polls
    ``GET /tasks/{task_id}`` for progress updates.

    The SSI job pushes investigation results back to core via the
    ``CoreBridge`` when ``push_to_core=True`` (default), creating a
    case record with attached evidence.

    Args:
        payload: Investigation parameters (URL, scan type, etc.).
        user: Authenticated user (must have ``analyst`` role or above).

    Returns:
        Task ID and initial status for the investigation.
    """
    settings = get_settings()
    task_id = f"ssi-{uuid.uuid4().hex[:12]}"

    # Register the task immediately so the UI can poll it.
    TASK_STATUS[task_id] = {
        "status": "queued",
        "message": f"SSI investigation queued for {payload.url}",
        "url": payload.url,
        "scan_type": payload.scan_type,
        "triggered_by": user.get("username", "unknown"),
    }

    logger.info(
        "SSI investigation requested: url=%s scan_type=%s by=%s task_id=%s",
        payload.url,
        payload.scan_type,
        user.get("username"),
        task_id,
    )

    is_local = settings.env == "local"
    ssi_job = getattr(settings, "ssi_job", None)
    job_name = getattr(ssi_job, "job_name", "ssi-investigate") if ssi_job else "ssi-investigate"

    if is_local:
        _trigger_local_investigation(
            task_id=task_id,
            url=payload.url,
            scan_type=payload.scan_type,
            push_to_core=payload.push_to_core,
            trigger_dossier=payload.trigger_dossier,
            dataset=payload.dataset,
        )
        return {
            "task_id": task_id,
            "status": "queued",
            "message": f"SSI investigation started locally for {payload.url}",
            "job_name": None,
        }

    # Cloud environments: trigger Cloud Run Job
    project = getattr(ssi_job, "project", None) or "i4g-dev"
    region = getattr(ssi_job, "region", None) or "us-central1"
    service_account = getattr(ssi_job, "service_account", None)

    # Build the task-status callback URL so the SSI job can POST updates.
    api_base = getattr(ssi_job, "core_api_url", None) or ""
    if not api_base:
        # Derive from the current request context — not available in this
        # scope, so fall back to the settings-based API URL.
        api_base = f"https://api.intelligenceforgood.org"

    env_overrides: dict[str, str] = {
        "SSI_JOB__URL": payload.url,
        "SSI_JOB__SCAN_TYPE": payload.scan_type,
        "SSI_JOB__PUSH_TO_CORE": str(payload.push_to_core).lower(),
        "SSI_JOB__TRIGGER_DOSSIER": str(payload.trigger_dossier).lower(),
        "SSI_JOB__DATASET": payload.dataset,
        "I4G_TASK_ID": task_id,
        "I4G_TASK_STATUS_URL": f"{api_base}/tasks",
    }

    try:
        op_name = _trigger_cloud_run_job(
            project=project,
            region=region,
            job_name=job_name,
            env_overrides=env_overrides,
            service_account=service_account,
        )
        TASK_STATUS[task_id] = {
            "status": "running",
            "message": f"Cloud Run Job triggered for {payload.url}",
            "operation": op_name,
        }
        return {
            "task_id": task_id,
            "status": "running",
            "message": f"SSI investigation triggered via Cloud Run Job",
            "job_name": job_name,
        }
    except Exception as exc:
        logger.error("Failed to trigger SSI Cloud Run Job: %s", exc, exc_info=True)
        TASK_STATUS[task_id] = {
            "status": "failed",
            "message": f"Failed to trigger Cloud Run Job: {exc}",
        }
        raise HTTPException(status_code=502, detail=f"Failed to trigger SSI investigation: {exc}") from exc


@router.get(
    "/ssi/{task_id}",
    summary="Get SSI investigation status",
    response_model=None,
)
def get_ssi_investigation_status(
    task_id: str,
    user: dict[str, str] = Depends(require_token),
) -> dict[str, Any]:
    """Get the status of an SSI investigation by task ID.

    Convenience alias that delegates to the general ``/tasks/{task_id}``
    endpoint.  Returns the same payload shape.

    Args:
        task_id: The task identifier returned by ``POST /investigations/ssi``.
        user: Authenticated user.

    Returns:
        Task status dict.
    """
    if task_id not in TASK_STATUS:
        return {"task_id": task_id, "status": "unknown", "message": "Task not found"}
    return {"task_id": task_id, **TASK_STATUS[task_id]}
