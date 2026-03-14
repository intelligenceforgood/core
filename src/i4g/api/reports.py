"""Reports API surfaces for dossier artifacts."""

from __future__ import annotations

import contextlib
import json
import logging
import re
import uuid
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from i4g.api.auth import require_token
from i4g.api.camel import CamelModel
from i4g.api.response_models import DossierVerifyResponse, DriveAclResponse, ItemListResponse
from i4g.observability import Observability, get_observability
from i4g.reports.dossier_signatures import verify_manifest_payload
from i4g.reports.dossier_uploads import DossierUploader
from i4g.services.factories import build_dossier_queue_store
from i4g.settings import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"], dependencies=[Depends(require_token)])
ARTIFACTS_DIR = (get_settings().data_dir / "reports" / "dossiers").resolve()
_OBS: Observability = get_observability(component="reports_api")
_ALLOWED_ARTIFACTS = {
    "manifest": "manifest",
    "markdown": "markdown",
    "pdf": "pdf",
    "html": "html",
    "signature": "signature_manifest",
}

_SAFE_PLAN_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.\-]{0,127}$")


def _validate_plan_id(plan_id: str) -> str:
    """Validate ``plan_id`` against a safe character allowlist.

    Raises:
        HTTPException: 400 if ``plan_id`` contains path-traversal sequences
            or forbidden characters.
    """
    if not _SAFE_PLAN_ID.match(plan_id):
        raise HTTPException(status_code=400, detail=f"Invalid plan_id: {plan_id!r}")
    return plan_id


@router.get("/dossiers", response_model=ItemListResponse)
def list_dossiers(
    *,
    status: str = Query("completed", description="Queue status to filter (use 'all' for every entry)."),
    limit: int = Query(20, ge=1, le=200, description="Maximum number of dossier rows to return."),
    include_manifest: bool = Query(False, description="Include the full dossier manifest payload when true."),
) -> dict[str, Any]:
    """Return dossier queue entries along with manifest + signature metadata."""

    normalized_status = status.strip().lower()
    status_filter = None if not normalized_status or normalized_status == "all" else normalized_status
    tags = {"status": status_filter or "all"}
    try:
        store = build_dossier_queue_store()
        entries = store.list_plans(status=status_filter, limit=limit)
        records: list[dict[str, Any]] = []
        for entry in entries:
            plan_id = entry.get("plan_id")
            manifest_info = _load_manifest_details(plan_id, include_manifest=include_manifest)
            records.append(
                {
                    "plan_id": plan_id,
                    "status": entry.get("status"),
                    "queued_at": entry.get("queued_at"),
                    "updated_at": entry.get("updated_at"),
                    "warnings": entry.get("warnings") or [],
                    "error": entry.get("error"),
                    "payload": entry.get("payload"),
                    **manifest_info,
                }
            )
        _OBS.increment("reports.dossiers.list.success", tags=tags)
        _OBS.emit_event("reports.dossiers.list", status=status_filter or "all", count=len(records))
        return {"count": len(records), "items": records}
    except HTTPException:
        _OBS.increment("reports.dossiers.list.error", tags={**tags, "code": "http"})
        raise
    except Exception:
        _OBS.increment("reports.dossiers.list.error", tags={**tags, "code": "unhandled"})
        raise


@router.post("/dossiers/{plan_id}/verify", response_model=DossierVerifyResponse)
def verify_dossier(plan_id: str) -> dict[str, Any]:
    """Run an artifact verification pass for the provided dossier plan."""

    plan_id = _validate_plan_id(plan_id)
    logger.info("verify_dossier: plan_id=%s", plan_id)
    tags = {"plan_id": plan_id}
    manifest_info = _load_manifest_details(plan_id, include_manifest=False)
    signature_manifest = manifest_info.get("signature_manifest")
    signature_path = manifest_info.get("signature_manifest_path")
    if not signature_manifest:
        _OBS.increment("reports.dossiers.verify.error", tags={**tags, "code": "missing_signature"})
        raise HTTPException(status_code=404, detail=f"Signature manifest unavailable for plan {plan_id}")

    base_path = Path(signature_path).parent if signature_path else ARTIFACTS_DIR
    try:
        report = verify_manifest_payload(signature_manifest, base_path=base_path)
    except ValueError as exc:
        _OBS.increment("reports.dossiers.verify.error", tags={**tags, "code": "validation"})
        raise HTTPException(status_code=400, detail=f"Verification failed: {exc}") from exc

    metric_tags = {
        **tags,
        "all_verified": str(report.all_verified).lower(),
        "missing": str(report.missing_count),
        "mismatch": str(report.mismatch_count),
    }
    _OBS.increment("reports.dossiers.verify.success", tags=metric_tags)
    _OBS.emit_event(
        "reports.dossiers.verify",
        plan_id=plan_id,
        all_verified=report.all_verified,
        missing=report.missing_count,
        mismatch=report.mismatch_count,
    )

    return {
        "plan_id": plan_id,
        "algorithm": report.algorithm,
        "warnings": list(report.warnings),
        "missing_count": report.missing_count,
        "mismatch_count": report.mismatch_count,
        "all_verified": report.all_verified,
        "artifacts": [
            {
                "label": artifact.label,
                "path": str(artifact.path) if artifact.path else None,
                "expected_hash": artifact.expected_hash,
                "actual_hash": artifact.actual_hash,
                "exists": artifact.exists,
                "matches": artifact.matches,
                "size_bytes": artifact.size_bytes,
                "error": artifact.error,
            }
            for artifact in report.artifacts
        ],
    }


@router.get("/dossiers/{plan_id}/drive_acl", response_model=DriveAclResponse)
def fetch_drive_acl(plan_id: str) -> dict[str, Any]:
    """Return Drive folder metadata + permissions for portal ACL previews."""

    plan_id = _validate_plan_id(plan_id)
    tags = {"plan_id": plan_id}
    manifest_info = _load_manifest_details(plan_id, include_manifest=False)
    drive_info = (manifest_info.get("downloads") or {}).get("drive") or {}
    folder_id = drive_info.get("shared_drive_parent_id")
    if not folder_id:
        _OBS.increment("reports.dossiers.drive_acl.error", tags={**tags, "code": "missing_folder"})
        raise HTTPException(status_code=404, detail=f"Drive folder unavailable for plan {plan_id}")

    uploader = DossierUploader(drive_parent_id=folder_id)
    acl, warnings = uploader.fetch_acl(folder_id=folder_id)
    if acl is None:
        _OBS.increment("reports.dossiers.drive_acl.error", tags={**tags, "code": "unavailable"})
        raise HTTPException(status_code=503, detail=f"Drive ACL unavailable for plan {plan_id}")

    _OBS.increment("reports.dossiers.drive_acl.success", tags=tags)
    return {
        "plan_id": plan_id,
        "folder_id": acl.get("folder_id"),
        "folder_name": acl.get("name"),
        "link": acl.get("link"),
        "drive_id": acl.get("drive_id"),
        "permissions": acl.get("permissions") or [],
        "warnings": warnings,
    }


@router.get("/dossiers/{plan_id}/signature_manifest")
def fetch_signature_manifest(plan_id: str) -> dict[str, Any]:
    """Return the raw signature manifest for client-side verification flows."""

    plan_id = _validate_plan_id(plan_id)
    manifest_info = _load_manifest_details(plan_id, include_manifest=False)
    signature_manifest = manifest_info.get("signature_manifest")
    if not signature_manifest:
        raise HTTPException(status_code=404, detail=f"Signature manifest unavailable for plan {plan_id}")
    with contextlib.suppress(Exception):
        _OBS.increment("reports.dossiers.signature_manifest", tags={"plan_id": plan_id})
    return signature_manifest


@router.get("/dossiers/{plan_id}/download/{artifact}")
def download_dossier_artifact(plan_id: str, artifact: str) -> FileResponse:
    """Serve local dossier artifacts for portal/analyst download and client-side verification."""

    plan_id = _validate_plan_id(plan_id)
    normalized = artifact.strip().lower()
    if normalized not in _ALLOWED_ARTIFACTS:
        raise HTTPException(status_code=400, detail=f"Unsupported artifact '{artifact}'")

    manifest_info = _load_manifest_details(plan_id, include_manifest=False)
    local_downloads = manifest_info.get("downloads", {}).get("local", {})
    key = _ALLOWED_ARTIFACTS[normalized]
    path_str = local_downloads.get(key)
    if not path_str:
        raise HTTPException(status_code=404, detail=f"Artifact '{artifact}' not available for plan {plan_id}")

    path = Path(path_str).resolve()
    # Defense-in-depth: ensure the resolved path is within the artifacts tree.
    try:
        path.relative_to(ARTIFACTS_DIR)
    except ValueError:
        raise HTTPException(status_code=403, detail="Artifact path outside allowed directory")  # noqa: B904
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail=f"Artifact path missing for plan {plan_id}: {path}")
    with contextlib.suppress(Exception):  # Observability is best-effort
        _OBS.increment("reports.dossiers.download", tags={"artifact": key})
    return FileResponse(path)


def _load_manifest_details(plan_id: str, *, include_manifest: bool) -> dict[str, Any]:
    """Return manifest + signature metadata for ``plan_id``."""

    warnings: list[str] = []
    manifest_path = ARTIFACTS_DIR / f"{plan_id}.json"
    manifest_preview: dict[str, Any] | None = None
    manifest_payload: dict[str, Any] | None = None
    manifest_path_str: str | None = None

    if manifest_path.exists():
        manifest_path_str = str(manifest_path)
        try:
            manifest_preview = json.loads(manifest_path.read_text())
            if include_manifest:
                manifest_payload = manifest_preview
        except json.JSONDecodeError as exc:
            warnings.append(f"Failed to parse manifest {manifest_path}: {exc}")
    else:
        warnings.append(f"Manifest missing for plan {plan_id} at {manifest_path}")

    signature_manifest, signature_manifest_path_str = _load_signature_manifest(manifest_path, manifest_preview)
    signature_path_obj = Path(signature_manifest_path_str) if signature_manifest_path_str else None
    if signature_manifest is None:
        signature_path_obj = None
    downloads = _build_downloads(
        manifest_preview=manifest_preview,
        signature_manifest=signature_manifest,
        manifest_path=manifest_path if manifest_path.exists() else None,
        signature_path=signature_path_obj,
    )
    if signature_manifest is None and signature_manifest_path_str:
        warnings.append(f"Signature manifest missing or invalid at {signature_manifest_path_str}")

    return {
        "manifest_path": manifest_path_str,
        "manifest": manifest_payload,
        "signature_manifest_path": signature_manifest_path_str,
        "signature_manifest": signature_manifest,
        "artifact_warnings": warnings,
        "downloads": downloads,
    }


def _load_signature_manifest(
    manifest_path: Path, manifest_preview: dict[str, Any] | None
) -> tuple[dict[str, Any] | None, str | None]:
    """Load the signature manifest referenced by ``manifest_preview`` (if any)."""

    signature_path: Path | None = None
    if manifest_preview:
        signature_info = manifest_preview.get("signature_manifest") or {}
        raw_path = signature_info.get("path")
        if raw_path:
            candidate = Path(raw_path)
            signature_path = candidate if candidate.is_absolute() else manifest_path.parent / candidate
    if not signature_path:
        signature_path = manifest_path.with_suffix(".signatures.json")

    signature_path_str = str(signature_path) if signature_path else None
    if not signature_path:
        return None, None
    if not signature_path.exists():
        return None, signature_path_str
    try:
        return json.loads(signature_path.read_text()), signature_path_str
    except json.JSONDecodeError:
        return None, signature_path_str


def _build_downloads(
    *,
    manifest_preview: Mapping[str, Any] | None,
    signature_manifest: Mapping[str, Any] | None,
    manifest_path: Path | None,
    signature_path: Path | None,
) -> dict[str, Any]:
    """Return download metadata for local and uploaded artifacts."""

    base_dir = manifest_path.parent if manifest_path else ARTIFACTS_DIR
    exports = (manifest_preview or {}).get("exports") or {}
    template_render = (manifest_preview or {}).get("template_render") or {}
    plan_id = (manifest_preview or {}).get("plan_id")
    local = {
        "manifest": str(manifest_path) if manifest_path else None,
        "markdown": _resolve_relative(template_render.get("path"), base_dir),
        "pdf": _resolve_relative(exports.get("pdf_path"), base_dir),
        "html": _resolve_relative(exports.get("html_path"), base_dir),
        "signature_manifest": str(signature_path) if signature_path else None,
    }
    api_urls = {}
    if plan_id:
        api_urls = {
            api_label: f"/reports/dossiers/{plan_id}/download/{api_label}"
            for api_label, label in _ALLOWED_ARTIFACTS.items()
            if local.get(label)
        }
    remote: list[dict[str, Any]] = []
    uploads_raw = signature_manifest.get("uploads") if signature_manifest else None
    uploads: Iterable[Mapping[str, Any]] | None = uploads_raw if isinstance(uploads_raw, list) else None
    if uploads:
        for upload in uploads:
            if not isinstance(upload, Mapping):
                continue
            remote.append(
                {
                    "label": str(upload.get("label") or "artifact"),
                    "remote_ref": upload.get("remote_ref"),
                    "hash": upload.get("hash"),
                    "algorithm": upload.get("algorithm"),
                    "size_bytes": upload.get("size_bytes"),
                }
            )
    drive_info = {
        "shared_drive_parent_id": (manifest_preview or {}).get("shared_drive_parent_id"),
    }
    return {"local": local, "remote": remote, "api": api_urls, "drive": drive_info}


def _resolve_relative(raw_path: object, base_dir: Path) -> str | None:
    """Resolve a path relative to *base_dir*, ensuring confinement.

    Returns ``None`` when the resolved path falls outside ``ARTIFACTS_DIR``.
    """
    if not raw_path:
        return None
    candidate = Path(str(raw_path))
    candidate = (base_dir / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    # Ensure the resolved path stays within the artifacts tree.
    try:
        candidate.relative_to(ARTIFACTS_DIR)
    except ValueError:
        return None
    return str(candidate)


# ---------------------------------------------------------------------------
# Report Generation & Library (S3-08, S3-09)
# ---------------------------------------------------------------------------

_TLP_DEFAULTS: dict[str, str] = {
    "executive_summary": "TLP:AMBER",
    "lea_dossier": "TLP:RED",
    "campaign_bulletin": "TLP:AMBER",
    "sar_supplement": "TLP:AMBER",
}

_VALID_TLP = {"TLP:WHITE", "TLP:GREEN", "TLP:AMBER", "TLP:RED"}


class ReportGenerateRequest(BaseModel):
    """Request body for report generation."""

    template: str
    scope: dict[str, Any] = {}
    options: dict[str, Any] = {}


class ReportLibraryItem(CamelModel):
    """Item in the report library listing."""

    report_id: str
    template: str
    scope: str = ""
    tlp: str = "TLP:AMBER"
    status: str = "completed"
    created_at: str | None = None
    created_by: str = "system"


@router.post("/generate")
def generate_report(
    payload: ReportGenerateRequest,
    user: dict = Depends(require_token),
) -> dict[str, Any]:
    """Queue a report for generation.

    Accepts a template identifier, scope (e.g., campaign_id, entity filter,
    date range), and options (TLP override, sections, header note).

    The TLP label defaults to the template default per D10 and can be
    overridden by admin-level users.

    Args:
        payload: Report generation request.
        user: Authenticated user context.

    Returns:
        Dict with report_id and status.
    """
    template = payload.template
    tlp = payload.options.get("tlp", _TLP_DEFAULTS.get(template, "TLP:AMBER"))
    if tlp not in _VALID_TLP:
        raise HTTPException(status_code=400, detail=f"Invalid TLP label: {tlp}")

    # Generate a report ID
    report_id = str(uuid.uuid4())

    # Audit log
    logger.info(
        "REPORT_GENERATE user=%s template=%s tlp=%s report_id=%s scope=%s",
        user.get("username", "unknown"),
        template,
        tlp,
        report_id,
        json.dumps(payload.scope)[:200],
    )

    # Store report metadata in artifacts directory
    report_dir = ARTIFACTS_DIR / "generated"
    report_dir.mkdir(parents=True, exist_ok=True)

    report_meta = {
        "report_id": report_id,
        "template": template,
        "tlp": tlp,
        "scope": payload.scope,
        "options": payload.options,
        "status": "queued",
        "generated_by": user.get("username", "unknown"),
        "generated_at": datetime.now(UTC).isoformat(),
    }
    meta_path = report_dir / f"{report_id}.json"
    meta_path.write_text(json.dumps(report_meta, indent=2))

    return {"report_id": report_id, "status": "queued", "tlp": tlp}


@router.get("/library")
def list_reports(
    limit: int = Query(50, ge=1, le=200, description="Max reports to return"),
) -> dict[str, Any]:
    """List generated reports with metadata.

    Scans the report artifacts directory for generated report metadata files.

    Args:
        limit: Maximum number of reports to return.

    Returns:
        Wrapped response with ``items`` and ``count``.
    """
    report_dir = ARTIFACTS_DIR / "generated"
    if not report_dir.exists():
        return {"items": [], "count": 0}

    items: list[ReportLibraryItem] = []
    for meta_file in sorted(report_dir.glob("*.json"), reverse=True)[:limit]:
        try:
            meta = json.loads(meta_file.read_text())
            report_id = meta.get("report_id", meta_file.stem)
            scope = meta.get("scope", {})
            scope_parts = []
            if scope.get("campaign_id"):
                scope_parts.append(f"Campaign: {scope['campaign_id'][:8]}")
            if scope.get("entity_type"):
                scope_parts.append(f"Entity: {scope['entity_type']}")
            if scope.get("date_range"):
                scope_parts.append(f"Period: {scope['date_range']}")

            items.append(
                ReportLibraryItem(
                    report_id=report_id,
                    template=meta.get("template", "unknown"),
                    scope="; ".join(scope_parts) if scope_parts else "Platform-wide",
                    tlp=meta.get("tlp", "TLP:AMBER"),
                    status=meta.get("status", "unknown"),
                    created_at=meta.get("generated_at"),
                    created_by=meta.get("generated_by", "system"),
                )
            )
        except (json.JSONDecodeError, OSError):
            continue

    return {"items": items, "count": len(items)}


@router.get("/{report_id}/download")
def download_report(report_id: str) -> FileResponse:
    """Download a generated report PDF.

    Args:
        report_id: The report UUID.

    Returns:
        PDF file response.

    Raises:
        HTTPException: 404 if report not found.
    """
    report_id = _validate_plan_id(report_id)
    report_dir = ARTIFACTS_DIR / "generated"

    # Look for a PDF file with the report ID
    pdf_path = report_dir / f"{report_id}.pdf"
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail=f"Report PDF not found: {report_id}")

    # Ensure path stays within artifacts
    resolved = pdf_path.resolve()
    try:
        resolved.relative_to(ARTIFACTS_DIR)
    except ValueError:
        raise HTTPException(status_code=403, detail="Path outside permitted directory")  # noqa: B904

    return FileResponse(resolved, media_type="application/pdf", filename=f"report-{report_id}.pdf")


# ---------------------------------------------------------------------------
# S5-15  Report Schedule endpoints
# ---------------------------------------------------------------------------


_VALID_CADENCE = {"once", "daily", "weekly", "monthly"}


class ReportScheduleRequest(CamelModel):
    """Request to create or update a report schedule."""

    template: str
    cadence: str
    scope: dict[str, Any] | None = None
    options: dict[str, Any] | None = None
    recipients: list[str] | None = None


class ReportScheduleResponse(CamelModel):
    """Report schedule representation."""

    schedule_id: str
    template: str
    cadence: str
    scope: dict[str, Any] | None = None
    options: dict[str, Any] | None = None
    recipients: list[str] | None = None
    is_active: bool = True
    created_by: str = "system"
    last_run_at: str | None = None
    next_run_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ReportScheduleUpdateRequest(CamelModel):
    """Request to update an existing report schedule."""

    template: str | None = None
    cadence: str | None = None
    scope: dict[str, Any] | None = None
    options: dict[str, Any] | None = None
    recipients: list[str] | None = None
    is_active: bool | None = None


def _normalize_schedule_scope(scope: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalize schedule scope keys for backward compatibility.

    Supports the previous UI payload shape using ``range`` and normalizes it
    to ``date_range`` used by worker jobs.
    """
    if scope is None:
        return None
    normalized = dict(scope)
    legacy_range = normalized.pop("range", None)
    if legacy_range is not None and "date_range" not in normalized:
        normalized["date_range"] = legacy_range
    return normalized


def _compute_next_run(cadence: str) -> datetime:
    """Compute the first ``next_run_at`` for a given cadence."""
    from datetime import timedelta

    now = datetime.now(UTC)
    if cadence == "daily":
        return now + timedelta(days=1)
    if cadence == "weekly":
        return now + timedelta(weeks=1)
    if cadence == "monthly":
        return now + timedelta(days=30)
    return now


@router.post("/schedules", response_model=ReportScheduleResponse, status_code=201)
def create_report_schedule(
    payload: ReportScheduleRequest,
    user: dict[str, str] = Depends(require_token),
) -> ReportScheduleResponse:
    """Create a recurring report schedule.

    Args:
        payload: Schedule details.
        user: Authenticated user.

    Returns:
        Created schedule.
    """
    if payload.cadence not in _VALID_CADENCE:
        raise HTTPException(status_code=400, detail=f"Invalid cadence: {payload.cadence}")

    from i4g.store.sql import build_engine, scheduled_reports

    schedule_id = str(uuid.uuid4())
    now_str = datetime.now(UTC).isoformat()
    next_run = _compute_next_run(payload.cadence)
    normalized_scope = _normalize_schedule_scope(payload.scope)

    engine = build_engine()
    with engine.begin() as conn:
        conn.execute(
            scheduled_reports.insert().values(
                schedule_id=schedule_id,
                template=payload.template,
                cadence=payload.cadence,
                scope=normalized_scope,
                options=payload.options,
                recipients=payload.recipients,
                created_by=user.get("email", "system"),
                is_active=True,
                next_run_at=next_run,
                created_at=now_str,
                updated_at=now_str,
            )
        )

    return ReportScheduleResponse(
        schedule_id=schedule_id,
        template=payload.template,
        cadence=payload.cadence,
        scope=normalized_scope,
        options=payload.options,
        recipients=payload.recipients,
        is_active=True,
        created_by=user.get("email", "system"),
        next_run_at=next_run.isoformat(),
        created_at=now_str,
        updated_at=now_str,
    )


@router.get("/schedules", response_model=list[ReportScheduleResponse])
def list_report_schedules(
    user: dict[str, str] = Depends(require_token),
) -> list[ReportScheduleResponse]:
    """List all report schedules.

    Args:
        user: Authenticated user.

    Returns:
        List of schedules.
    """
    import sqlalchemy as sa

    from i4g.store.sql import build_engine, scheduled_reports

    engine = build_engine()
    with engine.connect() as conn:
        rows = conn.execute(sa.select(scheduled_reports).order_by(scheduled_reports.c.created_at.desc())).fetchall()

    items: list[ReportScheduleResponse] = []
    for row in rows:
        items.append(
            ReportScheduleResponse(
                schedule_id=str(row.schedule_id),
                template=row.template,
                cadence=row.cadence,
                scope=row.scope,
                options=row.options,
                recipients=row.recipients,
                is_active=row.is_active,
                created_by=row.created_by,
                last_run_at=row.last_run_at.isoformat() if row.last_run_at else None,
                next_run_at=row.next_run_at.isoformat() if row.next_run_at else None,
                created_at=row.created_at.isoformat() if row.created_at else None,
                updated_at=row.updated_at.isoformat() if row.updated_at else None,
            )
        )
    return items


@router.put("/schedules/{schedule_id}", response_model=ReportScheduleResponse)
def update_report_schedule(
    schedule_id: str,
    payload: ReportScheduleUpdateRequest,
    user: dict[str, str] = Depends(require_token),
) -> ReportScheduleResponse:
    """Update a report schedule.

    Args:
        schedule_id: Schedule UUID.
        payload: Fields to update.
        user: Authenticated user.

    Returns:
        Updated schedule.
    """
    schedule_id = _validate_plan_id(schedule_id)

    if payload.cadence is not None and payload.cadence not in _VALID_CADENCE:
        raise HTTPException(status_code=400, detail=f"Invalid cadence: {payload.cadence}")

    import sqlalchemy as sa

    from i4g.store.sql import build_engine, scheduled_reports

    engine = build_engine()
    normalized_scope = _normalize_schedule_scope(payload.scope) if payload.scope is not None else None

    with engine.begin() as conn:
        existing = conn.execute(
            sa.select(scheduled_reports).where(scheduled_reports.c.schedule_id == schedule_id)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Schedule not found")

        updates: dict[str, Any] = {"updated_at": datetime.now(UTC).isoformat()}
        if payload.template is not None:
            updates["template"] = payload.template
        if payload.cadence is not None:
            updates["cadence"] = payload.cadence
            updates["next_run_at"] = _compute_next_run(payload.cadence)
        if normalized_scope is not None:
            updates["scope"] = normalized_scope
        if payload.options is not None:
            updates["options"] = payload.options
        if payload.recipients is not None:
            updates["recipients"] = payload.recipients
        if payload.is_active is not None:
            updates["is_active"] = payload.is_active

        conn.execute(scheduled_reports.update().where(scheduled_reports.c.schedule_id == schedule_id).values(**updates))

        row = conn.execute(
            sa.select(scheduled_reports).where(scheduled_reports.c.schedule_id == schedule_id)
        ).fetchone()

    return ReportScheduleResponse(
        schedule_id=str(row.schedule_id),
        template=row.template,
        cadence=row.cadence,
        scope=row.scope,
        options=row.options,
        recipients=row.recipients,
        is_active=row.is_active,
        created_by=row.created_by,
        last_run_at=row.last_run_at.isoformat() if row.last_run_at else None,
        next_run_at=row.next_run_at.isoformat() if row.next_run_at else None,
        created_at=row.created_at.isoformat() if row.created_at else None,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


@router.delete("/schedules/{schedule_id}")
def delete_report_schedule(
    schedule_id: str,
    user: dict[str, str] = Depends(require_token),
) -> dict[str, bool]:
    """Delete a report schedule.

    Args:
        schedule_id: Schedule UUID.
        user: Authenticated user.

    Returns:
        Deletion confirmation.
    """
    schedule_id = _validate_plan_id(schedule_id)

    from i4g.store.sql import build_engine, scheduled_reports

    engine = build_engine()
    with engine.begin() as conn:
        result = conn.execute(scheduled_reports.delete().where(scheduled_reports.c.schedule_id == schedule_id))
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Schedule not found")
    return {"deleted": True}


__all__ = ["router"]
