"""Evidence download, upload, and batch-export endpoints.

Routes are mounted on the cases router at ``/cases/{case_id}/evidence/...``.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import uuid
import zipfile
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse

from i4g.api.auth import require_role, require_token
from i4g.api.camel import CamelModel
from i4g.services.factories import build_evidence_storage
from i4g.store.sql import cases, source_documents
from i4g.store.sql import session_factory as build_sql_session_factory

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/cases/{case_id}/evidence",
    tags=["evidence"],
    dependencies=[Depends(require_token)],
)


# --- Response schemas ---


class EvidenceMetadata(CamelModel):
    """Metadata for a single evidence artifact."""

    document_id: str
    title: str | None = None
    source_url: str | None = None
    mime_type: str | None = None
    file_sha256: str | None = None
    ingested_at: str | None = None
    text_sha256: str | None = None
    available: bool = False


class EvidenceListResponse(CamelModel):
    """List of evidence artifacts for a case."""

    case_id: str
    documents: list[EvidenceMetadata]


# --- Helpers ---


def _get_case_or_404(session: Any, case_id: str) -> None:
    """Raise 404 if *case_id* does not exist."""
    row = session.execute(
        sa.select(cases.c.case_id).where(cases.c.case_id == case_id)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")


def _get_document_row(session: Any, case_id: str, doc_id: str) -> Any:
    """Fetch source_document row or raise 404."""
    row = session.execute(
        sa.select(source_documents).where(
            source_documents.c.case_id == case_id,
            source_documents.c.document_id == doc_id,
        )
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    return row


# --- Endpoints ---


@router.get("", summary="List evidence for a case", response_model=EvidenceListResponse)
def list_evidence(case_id: str) -> EvidenceListResponse:
    """Return metadata for all source documents associated with *case_id*."""

    sf = build_sql_session_factory()
    evidence = build_evidence_storage()

    with sf() as session:
        _get_case_or_404(session, case_id)
        rows = session.execute(
            sa.select(source_documents).where(source_documents.c.case_id == case_id)
        ).fetchall()

    documents: list[EvidenceMetadata] = []
    for row in rows:
        mapping = row._mapping
        source_url = mapping.get("source_url")
        available = False
        if source_url:
            try:
                available = evidence.exists(source_url)
            except Exception:
                logger.debug("Could not check existence of %s", source_url)

        ingested_at = mapping.get("ingested_at")
        if isinstance(ingested_at, datetime):
            ingested_at = ingested_at.isoformat()

        documents.append(
            EvidenceMetadata(
                document_id=str(mapping["document_id"]),
                title=mapping.get("title"),
                source_url=source_url,
                mime_type=mapping.get("mime_type"),
                file_sha256=mapping.get("file_sha256"),
                ingested_at=ingested_at,
                text_sha256=mapping.get("text_sha256"),
                available=available,
            )
        )

    return EvidenceListResponse(case_id=case_id, documents=documents)


@router.get(
    "/export",
    summary="Batch evidence export (ZIP)",
    dependencies=[Depends(require_role("analyst"))],
)
def export_evidence(case_id: str) -> StreamingResponse:
    """Export all evidence files for a case as a ZIP archive with a manifest.

    The archive contains:
    - Each evidence file stored under its original filename.
    - ``manifest.json`` with chain-of-custody metadata (hashes, timestamps).

    Requires ``analyst`` role.
    """

    sf = build_sql_session_factory()
    evidence = build_evidence_storage()

    with sf() as session:
        _get_case_or_404(session, case_id)
        rows = session.execute(
            sa.select(source_documents).where(source_documents.c.case_id == case_id)
        ).fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail="No documents found for this case")

    # Build ZIP in memory
    buf = io.BytesIO()
    manifest_entries: list[dict[str, Any]] = []
    files_included = 0

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        seen_names: dict[str, int] = {}

        for row in rows:
            mapping = row._mapping
            doc_id = str(mapping["document_id"])
            source_url = mapping.get("source_url")
            title = mapping.get("title")

            entry: dict[str, Any] = {
                "document_id": doc_id,
                "title": title,
                "source_url": source_url,
                "mime_type": mapping.get("mime_type"),
                "text_sha256": mapping.get("text_sha256"),
                "file_sha256": mapping.get("file_sha256"),
                "ingested_at": _safe_iso(mapping.get("ingested_at")),
                "captured_at": _safe_iso(mapping.get("captured_at")),
            }

            if source_url:
                retrieved = None
                try:
                    retrieved = evidence.retrieve(source_url)
                except Exception:
                    logger.warning("Failed to retrieve evidence %s for doc %s", source_url, doc_id)

                if retrieved is not None:
                    # Deduplicate filenames within the archive
                    archive_name = retrieved.file_name
                    if archive_name in seen_names:
                        seen_names[archive_name] += 1
                        base, _, ext = archive_name.rpartition(".")
                        if ext:
                            archive_name = f"{base}_{seen_names[archive_name]}.{ext}"
                        else:
                            archive_name = f"{archive_name}_{seen_names[archive_name]}"
                    else:
                        seen_names[archive_name] = 0

                    zf.writestr(archive_name, retrieved.data)
                    entry["archive_file"] = archive_name
                    entry["download_sha256"] = retrieved.checksum_sha256
                    entry["size_bytes"] = retrieved.size_bytes
                    files_included += 1

            manifest_entries.append(entry)

        manifest = {
            "case_id": case_id,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "total_documents": len(rows),
            "files_included": files_included,
            "documents": manifest_entries,
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="evidence_{case_id}.zip"',
        },
    )


@router.get(
    "/{doc_id}",
    summary="Download evidence file",
    dependencies=[Depends(require_role("analyst"))],
)
def download_evidence(case_id: str, doc_id: str) -> Response:
    """Serve the evidence file for a specific source document.

    Requires ``analyst`` role. Resolves ``source_url`` from the
    ``source_documents`` table and streams the file from the configured
    evidence backend (local filesystem or GCS).
    """

    sf = build_sql_session_factory()
    evidence = build_evidence_storage()

    with sf() as session:
        _get_case_or_404(session, case_id)
        row = _get_document_row(session, case_id, doc_id)

    mapping = row._mapping
    source_url = mapping.get("source_url")
    if not source_url:
        raise HTTPException(status_code=404, detail="No evidence file linked to this document")

    retrieved = evidence.retrieve(source_url)
    if retrieved is None:
        raise HTTPException(status_code=404, detail="Evidence file not found at storage location")

    content_type = retrieved.content_type or mapping.get("mime_type") or "application/octet-stream"
    file_name = retrieved.file_name

    return Response(
        content=retrieved.data,
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{file_name}"',
            "X-Evidence-SHA256": retrieved.checksum_sha256,
        },
    )


# --- Utility ---


def _safe_iso(val: Any) -> str | None:
    """Convert a datetime to ISO string, or pass through strings."""
    if isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, str):
        return val
    return None


# --- Evidence upload endpoint (used by SSI CoreBridge) ---


class EvidenceUploadResponse(CamelModel):
    """Response for evidence file upload."""

    document_id: str
    case_id: str
    title: str


@router.post("", summary="Upload evidence file", response_model=EvidenceUploadResponse, status_code=201)
def upload_evidence(case_id: str, file: UploadFile) -> EvidenceUploadResponse:
    """Upload an evidence file and record it as a source document.

    The file is persisted via the configured evidence storage backend
    (local filesystem / GCS) and a ``source_documents`` row is created
    linking the artifact to *case_id*.

    Args:
        case_id: Parent case.
        file: Uploaded file.

    Returns:
        The new ``document_id`` and metadata.
    """
    sf = build_sql_session_factory()
    evidence = build_evidence_storage()

    with sf() as session:
        _get_case_or_404(session, case_id)

    # Read file content
    content = file.file.read()
    file_sha = hashlib.sha256(content).hexdigest()
    file_name = file.filename or "unknown"
    mime_type = file.content_type or "application/octet-stream"

    # Persist via evidence storage backend
    storage_key = f"cases/{case_id}/{file_name}"
    evidence.store(storage_key, content)

    # Create source_documents row
    doc_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    with sf() as session:
        session.execute(
            sa.insert(source_documents).values(
                document_id=doc_id,
                case_id=case_id,
                title=file_name,
                source_url=storage_key,
                mime_type=mime_type,
                file_sha256=file_sha,
                ingested_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()

    logger.info("Uploaded evidence %s (%s) to case %s", file_name, doc_id, case_id)
    return EvidenceUploadResponse(document_id=doc_id, case_id=case_id, title=file_name)
