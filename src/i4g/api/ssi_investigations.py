"""SSI investigation history and detail endpoints.

Provides read endpoints for past SSI investigations stored in the core
database.  These replace the equivalent endpoints from the standalone
``ssi-api`` service (``ssi.api.investigation_routes``).

* ``GET /investigations/ssi/history`` — paginated list of investigations
* ``GET /investigations/ssi/active`` — currently active investigations (stub)
* ``GET /investigations/ssi/{scan_id}`` — full detail for a scan

**Routing note:** These routes are registered *before* the existing
``GET /investigations/ssi/{task_id}`` convenience alias (in
``investigations.py``), which means that alias is effectively shadowed.
Callers should use ``GET /tasks/{task_id}`` for task-status polling
instead.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from i4g.api.auth import require_role, require_token
from i4g.api.camel import CamelModel
from i4g.services.factories import build_ssi_store

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/investigations/ssi",
    tags=["ssi"],
    dependencies=[Depends(require_token)],
)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class InvestigationListResponse(CamelModel):
    """Paginated list of investigation summaries."""

    items: list[dict[str, Any]]
    count: int
    limit: int
    offset: int


class InvestigationDetailResponse(CamelModel):
    """Full investigation detail with related records."""

    scan: dict[str, Any]
    wallets: list[dict[str, Any]]
    pii_exposures: list[dict[str, Any]]
    agent_actions: list[dict[str, Any]]


class ActiveInvestigationsResponse(CamelModel):
    """List of currently active (running) investigations."""

    active: list[dict[str, Any]]
    count: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialize_datetimes(row: dict[str, Any]) -> dict[str, Any]:
    """Convert datetime values to ISO-8601 strings in-place.

    Args:
        row: A dict whose values may include ``datetime`` objects.

    Returns:
        The same dict with datetimes converted to strings.
    """
    for key, val in row.items():
        if hasattr(val, "isoformat"):
            row[key] = val.isoformat()
    return row


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/history", response_model=InvestigationListResponse)
def list_investigations(
    domain: str | None = Query(None, description="Filter by domain."),
    status: str | None = Query(None, description="Filter by status (completed, failed, running)."),
    limit: int = Query(50, ge=1, le=200, description="Page size."),
    offset: int = Query(0, ge=0, description="Page offset."),
    _user: dict = Depends(require_role("analyst")),
) -> dict[str, Any]:
    """Return a paginated list of historical SSI investigations.

    Args:
        domain: Optional domain filter.
        status: Optional status filter.
        limit: Page size (1–200, default 50).
        offset: Pagination offset.

    Returns:
        Paginated list of investigation summaries.
    """
    store = build_ssi_store()
    scans = store.list_scans(domain=domain, status=status, limit=limit, offset=offset)
    for scan in scans:
        _serialize_datetimes(scan)
    return {"items": scans, "count": len(scans), "limit": limit, "offset": offset}


@router.get("/active", response_model=ActiveInvestigationsResponse)
def list_active_investigations(
    _user: dict = Depends(require_role("analyst")),
) -> dict[str, Any]:
    """List currently active (running) investigations.

    In the consolidated architecture, active investigation state lives
    in the SSI Job process.  This endpoint returns an empty list as a
    stub; Phase E (WebSocket Decision) will determine how live
    monitoring works across the gateway.

    Returns:
        Empty list of active investigations.
    """
    return {"active": [], "count": 0}


@router.get("/{scan_id}", response_model=InvestigationDetailResponse)
def get_investigation(
    scan_id: str,
    _user: dict = Depends(require_role("analyst")),
) -> dict[str, Any]:
    """Return full detail for a single SSI investigation.

    Includes the scan record, harvested wallets, PII exposures,
    and agent action trail.

    Args:
        scan_id: UUID of the site_scans row.

    Returns:
        Investigation detail with all related records.

    Raises:
        HTTPException: 404 if the scan does not exist.
    """
    store = build_ssi_store()
    scan = store.get_scan(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Investigation not found.")

    wallets = store.get_wallets(scan_id)
    pii_exposures = store.get_pii_exposures(scan_id)
    agent_actions = store.get_agent_actions(scan_id)

    _serialize_datetimes(scan)
    for collection in [wallets, pii_exposures, agent_actions]:
        for row in collection:
            _serialize_datetimes(row)

    return {
        "scan": scan,
        "wallets": wallets,
        "pii_exposures": pii_exposures,
        "agent_actions": agent_actions,
    }


@router.patch("/{scan_id}")
def update_investigation(
    scan_id: str,
    payload: dict[str, Any],
    _user: dict = Depends(require_token),
) -> dict[str, Any]:
    """Update a scan row with completion data from the SSI job.

    Called by the SSI Cloud Run Job after investigation completes to
    write the GCS evidence path, risk score, case ID, and final status
    back to the pre-created ``site_scans`` row.

    Args:
        scan_id: UUID of the site_scans row.
        payload: Fields to update (status, evidence_path, risk_score, etc.).

    Returns:
        Confirmation dict with the updated scan_id.

    Raises:
        HTTPException: 404 if the scan does not exist.
    """
    store = build_ssi_store()
    scan = store.get_scan(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Investigation not found.")

    # Whitelist allowed fields to prevent arbitrary column writes.
    allowed_fields = {
        "status", "evidence_path", "evidence_zip_sha256", "risk_score",
        "case_id", "classification_result", "error_message",
        "duration_seconds", "passive_result", "active_result",
        "wallet_count", "total_cost_usd", "llm_input_tokens",
        "llm_output_tokens", "taxonomy_version",
    }
    update_fields = {k: v for k, v in payload.items() if k in allowed_fields and v is not None}

    if update_fields:
        store.update_scan(scan_id, **update_fields)
        logger.info("Updated scan %s with fields: %s", scan_id, list(update_fields.keys()))

    return {"scan_id": scan_id, "updated": True}
