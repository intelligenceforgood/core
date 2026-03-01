"""SSI investigation trigger endpoints for the analyst console.

Provides ``POST /investigations/ssi`` to launch an SSI Cloud Run Job
that investigates a suspicious URL.  The endpoint returns a task ID
that the caller polls via ``GET /tasks/{task_id}`` for progress.

**Phase 3 (3.1, 3.2):** Core API triggers SSI investigations and
tracks their progress via the shared TASK_STATUS system.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import uuid
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from i4g.api.auth import require_role, require_token
from i4g.api.camel import CamelModel
from i4g.services.factories import build_ssi_store
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


class SsiInvestigationStatusResponse(CamelModel):
    """Response for SSI investigation status queries."""

    task_id: str
    status: str
    message: str = ""


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
    scan_id: str,
    url: str,
    scan_type: str,
    push_to_core: bool,
    trigger_dossier: bool,
    dataset: str,
) -> None:
    """Run an SSI investigation locally via subprocess for local-dev.

    Fires ``ssi job investigate`` in a background subprocess so the API
    returns immediately.  Task status updates are posted back to the
    local core API via HTTP (``I4G_TASK_STATUS_URL``) and merged into
    the in-memory ``TASK_STATUS`` dict.  The DB-backed poll path
    (``get_task_status`` reads from ``site_scans``) provides the
    authoritative completion signal.

    Args:
        task_id: Task identifier for status tracking.
        url: URL to investigate.
        scan_type: Investigation mode.
        push_to_core: Whether to push results to core.
        trigger_dossier: Whether to trigger dossier generation.
        dataset: Dataset label.
    """
    env_vars = {
        "SSI_JOB__URL": url,
        "SSI_JOB__SCAN_TYPE": scan_type,
        "SSI_JOB__PUSH_TO_CORE": str(push_to_core).lower(),
        "SSI_JOB__TRIGGER_DOSSIER": str(trigger_dossier).lower(),
        "SSI_JOB__DATASET": dataset,
        "SSI_JOB__SCAN_ID": scan_id,
        "I4G_TASK_ID": task_id,
        # Point the TaskStatusReporter at the local core API so the
        # subprocess can post progress updates (running → completed)
        # back to the in-memory TASK_STATUS dict via HTTP.
        "I4G_TASK_STATUS_URL": "http://localhost:8000/tasks",
    }

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
    except OSError as exc:
        TASK_STATUS[task_id] = {
            "status": "failed",
            "message": "SSI package not available locally. Install ssi to use local investigation mode.",
        }
        logger.warning("SSI not available locally — cannot run investigation: %s", exc)


def _trigger_cloud_run_service(
    *,
    service_url: str,
    url: str,
    scan_type: str,
    scan_id: str,
    push_to_core: bool,
    dataset: str,
) -> None:
    """Trigger an SSI investigation via the Cloud Run Service endpoint.

    Sends an HTTP POST to ``{service_url}/jobs/investigate`` with a
    Google-issued OIDC identity token for service-to-service auth.
    Cloud Run validates the token automatically.

    Args:
        service_url: Base URL of the SSI Cloud Run Service.
        url: Target URL to investigate.
        scan_type: Investigation mode (passive/active/full).
        scan_id: Pre-assigned scan ID.
        push_to_core: Whether to create a case record in core.
        dataset: Dataset label for the core case.

    Raises:
        RuntimeError: When the HTTP call fails or the service returns
            a non-2xx response.
    """
    import httpx

    endpoint = f"{service_url.rstrip('/')}/jobs/investigate"
    payload = {
        "url": url,
        "scan_type": scan_type,
        "scan_id": scan_id,
        "push_to_core": push_to_core,
        "dataset": dataset,
    }

    headers: dict[str, str] = {}

    # Acquire an OIDC identity token for service-to-service auth.
    # In local/test environments the google.auth libraries may not be
    # available — skip the token in that case (the service won't
    # require it locally).
    try:
        import google.auth.transport.requests
        import google.oauth2.id_token

        auth_request = google.auth.transport.requests.Request()
        token = google.oauth2.id_token.fetch_id_token(auth_request, audience=service_url)
        headers["Authorization"] = f"Bearer {token}"
    except Exception as exc:
        logger.warning("Could not acquire OIDC token for SSI service (will attempt without): %s", exc)

    logger.info("Triggering SSI service at %s for %s (scan_id=%s)", endpoint, url, scan_id)

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(endpoint, json=payload, headers=headers)
            response.raise_for_status()
            logger.info("SSI service accepted investigation: %s", response.json())
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"SSI service returned {exc.response.status_code}: {exc.response.text}"
        ) from exc
    except httpx.RequestError as exc:
        raise RuntimeError(f"Failed to reach SSI service at {endpoint}: {exc}") from exc


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
    """Trigger an SSI scam-site investigation.

    Creates a task entry in the TASK_STATUS store and triggers the SSI
    investigation via one of three paths:
    - **Local:** subprocess (``ssi job investigate``)
    - **Cloud, mode=service:** HTTP POST to the SSI Cloud Run Service
    - **Cloud, mode=job:** Cloud Run Jobs API (legacy)

    The client polls ``GET /tasks/{task_id}`` for progress updates.

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

    # Extract domain slug for the scan record.
    try:
        domain = urlparse(payload.url if "://" in payload.url else f"https://{payload.url}").netloc
        if domain.startswith("www."):
            domain = domain[4:]
    except Exception:
        domain = None

    # Create the scan row *before* launching the job so that:
    # 1. get_task_status can poll the scan from the DB.
    # 2. The SSI job uses the same scan_id as its investigation_id.
    scan_id = str(uuid.uuid4())
    try:
        ssi_store = build_ssi_store()
        ssi_store.create_scan(
            scan_id=scan_id,
            url=payload.url,
            scan_type=payload.scan_type,
            domain=domain,
        )
        logger.info("Pre-created scan %s for %s", scan_id, payload.url)
    except Exception as exc:
        logger.warning("Failed to pre-create scan row (will continue): %s", exc)

    # Register the task immediately so the UI can poll it.
    TASK_STATUS[task_id] = {
        "status": "queued",
        "message": f"SSI investigation queued for {payload.url}",
        "url": payload.url,
        "scan_type": payload.scan_type,
        "scan_id": scan_id,
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
    ssi_job = settings.ssi_job
    job_name = ssi_job.job_name

    if is_local:
        _trigger_local_investigation(
            task_id=task_id,
            scan_id=scan_id,
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

    # Cloud environments: dispatch based on ssi_job.mode
    if ssi_job.mode == "service":
        # Cloud Run Service path — HTTP POST to SSI service
        try:
            _trigger_cloud_run_service(
                service_url=ssi_job.service_url,
                url=payload.url,
                scan_type=payload.scan_type,
                scan_id=scan_id,
                push_to_core=payload.push_to_core,
                dataset=payload.dataset,
            )
            TASK_STATUS[task_id] = {
                "status": "running",
                "message": f"SSI service triggered for {payload.url}",
                "scan_id": scan_id,
            }
            return {
                "task_id": task_id,
                "status": "running",
                "message": "SSI investigation triggered via Cloud Run Service",
                "job_name": None,
            }
        except Exception as exc:
            logger.error("Failed to trigger SSI Cloud Run Service: %s", exc, exc_info=True)
            TASK_STATUS[task_id] = {
                "status": "failed",
                "message": f"Failed to trigger SSI service: {exc}",
            }
            raise HTTPException(
                status_code=502, detail=f"Failed to trigger SSI investigation: {exc}"
            ) from exc

    # Cloud Run Job path (default)
    project = ssi_job.project
    region = ssi_job.region
    service_account = ssi_job.service_account
    api_base = ssi_job.core_api_url

    env_overrides: dict[str, str] = {
        "SSI_JOB__URL": payload.url,
        "SSI_JOB__SCAN_TYPE": payload.scan_type,
        "SSI_JOB__PUSH_TO_CORE": str(payload.push_to_core).lower(),
        "SSI_JOB__TRIGGER_DOSSIER": str(payload.trigger_dossier).lower(),
        "SSI_JOB__DATASET": payload.dataset,
        "SSI_JOB__SCAN_ID": scan_id,
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
            "scan_id": scan_id,
            "operation": op_name,
        }
        return {
            "task_id": task_id,
            "status": "running",
            "message": "SSI investigation triggered via Cloud Run Job",
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
    response_model=SsiInvestigationStatusResponse,
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
