"""SSI evidence and report download endpoints.

Provides download access to investigation evidence artifacts stored
either on the local filesystem (development) or in Google Cloud Storage
(production).  These replace the equivalent endpoints from the
standalone ``ssi-api`` service.

* ``GET /investigations/ssi/{scan_id}/evidence-bundle`` — evidence ZIP
* ``GET /investigations/ssi/{scan_id}/lea-package`` — LEA evidence package
* ``GET /investigations/ssi/{scan_id}/report.pdf`` — PDF investigation report

Evidence assets are located via the ``evidence_path`` column on the
``site_scans`` table.  In local mode this is a filesystem directory;
in cloud mode it is a GCS prefix (``gs://bucket/prefix/scan_id/``).
"""

from __future__ import annotations

import io
import json
import logging
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse, Response, StreamingResponse

from i4g.api.auth import require_role, require_token
from i4g.services.factories import build_ssi_store

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/investigations/ssi",
    tags=["ssi", "evidence"],
    dependencies=[Depends(require_token)],
)


# ---------------------------------------------------------------------------
# GCS helpers (lazy-loaded)
# ---------------------------------------------------------------------------


def _generate_signed_url(bucket_name: str, blob_name: str, expiry_hours: int = 24) -> str:
    """Generate a time-limited GCS signed URL.

    Args:
        bucket_name: GCS bucket name.
        blob_name: Object key within the bucket.
        expiry_hours: URL validity in hours.

    Returns:
        HTTPS signed URL.

    Raises:
        RuntimeError: If ``google-cloud-storage`` is not installed.
    """
    try:
        from datetime import timedelta

        from google.cloud.storage import Client
    except ImportError as exc:
        raise RuntimeError(
            "google-cloud-storage is required for GCS evidence access. "
            "Install it with: pip install google-cloud-storage"
        ) from exc

    client = Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    return blob.generate_signed_url(expiration=timedelta(hours=expiry_hours), method="GET")


def _parse_gcs_uri(uri: str) -> tuple[str, str]:
    """Parse a ``gs://bucket/key`` URI into (bucket, key).

    Args:
        uri: A ``gs://`` URI string.

    Returns:
        Tuple of (bucket_name, blob_key).

    Raises:
        ValueError: If the URI is not a valid ``gs://`` URI.
    """
    if not uri.startswith("gs://"):
        raise ValueError(f"Expected gs:// URI, got: {uri}")
    without_scheme = uri[5:]
    bucket, _, key = without_scheme.partition("/")
    return bucket, key


def _get_evidence_dir(scan: dict[str, Any]) -> Path | None:
    """Return the local evidence directory for a scan, or ``None``.

    Args:
        scan: Scan dict from ``SsiStore``.

    Returns:
        Local ``Path`` if evidence_path is a filesystem path and exists,
        otherwise ``None``.
    """
    evidence_path = scan.get("evidence_path")
    if not evidence_path:
        return None
    if str(evidence_path).startswith("gs://"):
        return None
    inv_dir = Path(evidence_path)
    if inv_dir.exists():
        return inv_dir
    return None


def _gcs_file_url(scan: dict[str, Any], filename: str) -> str | None:
    """Generate a GCS signed URL for a file within the evidence directory.

    Args:
        scan: Scan dict from ``SsiStore``.
        filename: Filename relative to the evidence directory.

    Returns:
        Signed URL string, or ``None`` if evidence_path is not a GCS URI.
    """
    evidence_path = scan.get("evidence_path")
    if not evidence_path or not str(evidence_path).startswith("gs://"):
        return None
    try:
        bucket, prefix = _parse_gcs_uri(str(evidence_path))
        blob_name = f"{prefix.rstrip('/')}/{filename}"
        return _generate_signed_url(bucket, blob_name)
    except Exception:
        logger.warning("Failed to generate signed URL for %s/%s", evidence_path, filename, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/{scan_id}/evidence-bundle",
    responses={
        200: {"content": {"application/zip": {}}, "description": "Evidence ZIP (PDF + all artifacts)."},
        307: {"description": "Redirect to GCS signed URL."},
        404: {"description": "Investigation not found or evidence not available."},
    },
)
def download_evidence_bundle(
    scan_id: str,
    _user: dict = Depends(require_role("analyst")),
) -> Response:
    """Download the evidence ZIP bundle for an SSI investigation.

    In cloud mode, redirects to a time-limited GCS signed URL.
    In local mode, serves the file directly from disk.

    Args:
        scan_id: UUID of the site_scans row.

    Returns:
        Evidence ZIP file or redirect to signed URL.

    Raises:
        HTTPException: 404 if the scan or evidence is not found.
    """
    store = build_ssi_store()
    scan = store.get_scan(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Investigation not found.")

    evidence_path = scan.get("evidence_path")
    if not evidence_path:
        raise HTTPException(status_code=404, detail="No evidence path recorded for this investigation.")

    # GCS backend → signed URL redirect
    signed_url = _gcs_file_url(scan, "evidence.zip")
    if signed_url:
        return RedirectResponse(url=signed_url, status_code=307)

    # Local backend → serve file from disk
    inv_dir = _get_evidence_dir(scan)
    if not inv_dir:
        raise HTTPException(status_code=404, detail="Evidence directory not found.")

    zip_path = inv_dir / "evidence.zip"
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail="Evidence ZIP not found on disk.")

    return FileResponse(
        path=str(zip_path),
        filename=f"evidence_{scan_id[:8]}.zip",
        media_type="application/zip",
    )


@router.get(
    "/{scan_id}/lea-package",
    responses={
        200: {"content": {"application/zip": {}}, "description": "LEA-ready signed evidence package."},
        404: {"description": "Investigation not found or evidence not available."},
    },
)
def download_lea_package(
    scan_id: str,
    _user: dict = Depends(require_role("analyst")),
) -> Response:
    """Download a law-enforcement-ready evidence package.

    Assembles key evidence files (PDF report, STIX bundle, wallet
    manifest, LEO report, evidence ZIP) into a single package with
    a chain-of-custody manifest.

    In cloud mode, generates the package from GCS objects.  In local
    mode, reads from the filesystem.

    Args:
        scan_id: UUID of the site_scans row.

    Returns:
        ZIP archive containing LEA-relevant evidence files.

    Raises:
        HTTPException: 404 if the scan or evidence is not found.
    """
    store = build_ssi_store()
    scan = store.get_scan(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Investigation not found.")

    evidence_path = scan.get("evidence_path")
    if not evidence_path:
        raise HTTPException(status_code=404, detail="No evidence path recorded for this investigation.")

    inv_dir = _get_evidence_dir(scan)
    if not inv_dir:
        raise HTTPException(status_code=404, detail="Evidence directory not found on disk.")

    lea_files = [
        "report.pdf",
        "leo_evidence_report.md",
        "stix_bundle.json",
        "evidence.zip",
        "wallet_manifest.json",
    ]

    buf = io.BytesIO()
    included_count = 0

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname in lea_files:
            fpath = inv_dir / fname
            if fpath.exists():
                zf.write(fpath, fname)
                included_count += 1

        custody_info = {
            "scan_id": scan_id,
            "investigation_url": scan.get("url", ""),
            "evidence_zip_sha256": scan.get("evidence_zip_sha256", ""),
            "files_included": included_count,
            "package_note": (
                "This package is generated for law enforcement use. "
                "Verify evidence.zip integrity against evidence_zip_sha256."
            ),
        }
        zf.writestr("chain_of_custody.json", json.dumps(custody_info, indent=2))

    if included_count == 0:
        raise HTTPException(status_code=404, detail="No LEA-relevant evidence files found.")

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="lea_package_{scan_id[:8]}.zip"'},
    )


@router.get(
    "/{scan_id}/report.pdf",
    responses={
        200: {"content": {"application/pdf": {}}, "description": "Investigation PDF report."},
        307: {"description": "Redirect to GCS signed URL."},
        404: {"description": "Investigation not found or report not available."},
    },
)
def download_report_pdf(
    scan_id: str,
    _user: dict = Depends(require_role("analyst")),
) -> Response:
    """Download the PDF investigation report.

    In cloud mode, redirects to a time-limited GCS signed URL.
    In local mode, serves the file directly from disk.

    Args:
        scan_id: UUID of the site_scans row.

    Returns:
        PDF report or redirect to signed URL.

    Raises:
        HTTPException: 404 if the scan or report is not found.
    """
    store = build_ssi_store()
    scan = store.get_scan(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Investigation not found.")

    evidence_path = scan.get("evidence_path")
    if not evidence_path:
        raise HTTPException(status_code=404, detail="No evidence path recorded for this investigation.")

    # GCS backend → signed URL redirect
    signed_url = _gcs_file_url(scan, "report.pdf")
    if signed_url:
        return RedirectResponse(url=signed_url, status_code=307)

    # Local backend → serve from disk
    inv_dir = _get_evidence_dir(scan)
    if not inv_dir:
        raise HTTPException(status_code=404, detail="Evidence directory not found.")

    pdf_path = inv_dir / "report.pdf"
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF report not found on disk.")

    return FileResponse(
        path=str(pdf_path),
        filename=f"ssi_report_{scan_id[:8]}.pdf",
        media_type="application/pdf",
    )
