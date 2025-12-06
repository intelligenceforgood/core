"""Reports API surfaces for dossier artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

from fastapi import APIRouter, HTTPException, Query

from i4g.reports.dossier_signatures import verify_manifest_payload
from i4g.services.factories import build_dossier_queue_store
from i4g.settings import get_settings

router = APIRouter(prefix="/reports", tags=["reports"])
ARTIFACTS_DIR = (get_settings().data_dir / "reports" / "dossiers").resolve()


@router.get("/dossiers")
def list_dossiers(
    *,
    status: str = Query("completed", description="Queue status to filter (use 'all' for every entry)."),
    limit: int = Query(20, ge=1, le=200, description="Maximum number of dossier rows to return."),
    include_manifest: bool = Query(False, description="Include the full dossier manifest payload when true."),
) -> Dict[str, Any]:
    """Return dossier queue entries along with manifest + signature metadata."""

    normalized_status = status.strip().lower()
    status_filter = None if not normalized_status or normalized_status == "all" else normalized_status
    store = build_dossier_queue_store()
    entries = store.list_plans(status=status_filter, limit=limit)
    records: List[Dict[str, Any]] = []
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
    return {"count": len(records), "items": records}


@router.post("/dossiers/{plan_id}/verify")
def verify_dossier(plan_id: str) -> Dict[str, Any]:
    """Run an artifact verification pass for the provided dossier plan."""

    manifest_info = _load_manifest_details(plan_id, include_manifest=False)
    signature_manifest = manifest_info.get("signature_manifest")
    signature_path = manifest_info.get("signature_manifest_path")
    if not signature_manifest:
        raise HTTPException(status_code=404, detail=f"Signature manifest unavailable for plan {plan_id}")

    base_path = Path(signature_path).parent if signature_path else ARTIFACTS_DIR
    try:
        report = verify_manifest_payload(signature_manifest, base_path=base_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Verification failed: {exc}") from exc

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


def _load_manifest_details(plan_id: str, *, include_manifest: bool) -> Dict[str, Any]:
    """Return manifest + signature metadata for ``plan_id``."""

    warnings: List[str] = []
    manifest_path = ARTIFACTS_DIR / f"{plan_id}.json"
    manifest_preview: Dict[str, Any] | None = None
    manifest_payload: Dict[str, Any] | None = None
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
    manifest_path: Path, manifest_preview: Dict[str, Any] | None
) -> tuple[Dict[str, Any] | None, str | None]:
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
) -> Dict[str, Any]:
    """Return download metadata for local and uploaded artifacts."""

    base_dir = manifest_path.parent if manifest_path else ARTIFACTS_DIR
    exports = (manifest_preview or {}).get("exports") or {}
    template_render = (manifest_preview or {}).get("template_render") or {}
    local = {
        "manifest": str(manifest_path) if manifest_path else None,
        "markdown": _resolve_relative(template_render.get("path"), base_dir),
        "pdf": _resolve_relative(exports.get("pdf_path"), base_dir),
        "html": _resolve_relative(exports.get("html_path"), base_dir),
        "signature_manifest": str(signature_path) if signature_path else None,
    }
    remote: List[Dict[str, Any]] = []
    uploads: Iterable[Mapping[str, Any]] | None = None
    if signature_manifest:
        uploads = signature_manifest.get("uploads")  # type: ignore[assignment]
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
    return {"local": local, "remote": remote}


def _resolve_relative(raw_path: object, base_dir: Path) -> str | None:
    if not raw_path:
        return None
    candidate = Path(str(raw_path))
    if not candidate.is_absolute():
        candidate = (base_dir / candidate).resolve()
    return str(candidate)


__all__ = ["router"]
