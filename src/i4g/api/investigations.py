"""SSI investigation trigger endpoints for the analyst console.

Provides ``POST /investigations/ssi`` to launch an SSI investigation
via the SSI Cloud Run Service.  The endpoint returns a task ID that the
caller polls via ``GET /tasks/{task_id}`` for progress.

**Phase 3 (3.1, 3.2):** Core API triggers SSI investigations and
tracks their progress via the shared TASK_STATUS system.
"""

from __future__ import annotations

import logging
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


class SsiInvestigationStatusResponse(CamelModel):
    """Response for SSI investigation status queries."""

    task_id: str
    status: str
    message: str = ""


# ---------------------------------------------------------------------------
# Cloud Run Service trigger
# ---------------------------------------------------------------------------


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

    Sends an HTTP POST to ``{service_url}/trigger/investigate`` with a
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

    endpoint = f"{service_url.rstrip('/')}/trigger/investigate"
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
    investigation via the SSI Cloud Run Service (HTTP POST).

    The client polls ``GET /tasks/{task_id}`` for progress updates.

    The SSI service pushes investigation results back to core via the
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

    # Create the scan row *before* triggering the service so that:
    # 1. get_task_status can poll the scan from the DB.
    # 2. The SSI service uses the same scan_id as its investigation_id.
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

    ssi_cfg = settings.ssi
    service_url = ssi_cfg.service_url

    try:
        _trigger_cloud_run_service(
            service_url=service_url,
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
