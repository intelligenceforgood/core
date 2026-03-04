"""Reports API surfaces for dossier artifacts."""

from __future__ import annotations

import contextlib
import json
import logging
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from i4g.api.auth import require_token
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


__all__ = ["router"]
