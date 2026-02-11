"""Account list extraction API router."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from i4g.api.camel import CamelModel

try:
    from google.cloud import storage as gcs_storage
except ImportError:
    gcs_storage = None

from i4g.api.auth import is_valid_api_token
from i4g.services.account_list import AccountListRequest, AccountListResult, AccountListService, log_account_list_run
from i4g.services.account_list.exporters import AccountListExporter
from i4g.settings import Settings, get_settings
from i4g.store.review_store import ReviewStore

router = APIRouter(prefix="/accounts", tags=["accounts"])
LOGGER = logging.getLogger(__name__)
_REQUESTER_HEADERS = (
    "X-ACCOUNTLIST-REQUESTER",
    "X-REQUESTER",
    "X-ANALYST",
    "X-USER",
)
_AUDIT_ACTION = "account_list_run"


class AccountListRunSummary(CamelModel):
    """Serialized audit summary for a prior account list run."""

    request_id: str
    actor: str
    source: str
    generated_at: datetime
    indicator_count: int = 0
    source_count: int = 0
    warnings: List[str] = Field(default_factory=list)
    artifacts: Dict[str, str] = Field(default_factory=dict)
    categories: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AccountListRunResponse(CamelModel):
    """Envelope returned by the run-history endpoint."""

    runs: List[AccountListRunSummary]
    count: int


def get_account_list_service() -> AccountListService:
    """Dependency provider returning the shared AccountListService instance."""

    return AccountListService()


def get_review_store() -> ReviewStore:
    """Dependency provider for the shared ReviewStore instance."""
    from i4g.services.factories import build_review_store

    return build_review_store()


def require_account_list_key(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    """Validate the account-list API key header, leveraging nested settings."""
    if settings.identity.disable_auth:
        return

    config = settings.account_list
    if not config.enabled:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Account list disabled")
    if not config.require_api_key:
        return
    expected_key = config.api_key or settings.api.key
    if not expected_key:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="API key not configured")
    header_name = config.header_name or "X-ACCOUNTLIST-KEY"
    provided_key = request.headers.get(header_name)
    if not provided_key and header_name.lower() != "x-api-key":
        provided_key = request.headers.get("X-API-KEY")

    # Also support query parameter for direct browser downloads
    if not provided_key:
        provided_key = request.query_params.get("key")

    if provided_key != expected_key:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid account list API key")


def require_account_list_access(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    """Allow either analyst console tokens or the dedicated account list API key."""
    if settings.identity.disable_auth:
        return

    require_account_list_key(request=request, settings=settings)


def _resolve_actor(request: Request) -> str:
    """Infer the requester identity for audit logging."""

    for header in _REQUESTER_HEADERS:
        raw = request.headers.get(header)
        if raw:
            return f"accounts_api:{raw.strip()}"

    client_host = getattr(request.client, "host", None)
    if client_host:
        return f"accounts_api:{client_host}"
    return "accounts_api"


def _transform_artifacts(artifacts: Dict[str, str], request: Request) -> Dict[str, str]:
    """Convert local filesystem paths to download URLs for the client."""
    transformed = {}

    # Try to grab the current API key from the request header to embed in the link
    # This allows direct browser clicks to work without complex client-side blob handling.
    # Note: We check the default header name explicitly here since we don't have access to settings.
    current_key = (
        request.headers.get("X-ACCOUNTLIST-KEY") or request.headers.get("X-API-KEY") or request.query_params.get("key")
    )

    for key, path_or_url in artifacts.items():
        if path_or_url.startswith("gs://"):
            # Generate a signed URL for GCS artifacts
            if gcs_storage:
                try:
                    parts = path_or_url.replace("gs://", "").split("/", 1)
                    if len(parts) == 2:
                        bucket_name, blob_name = parts
                        # Reuse default credentials
                        client = gcs_storage.Client()
                        bucket = client.bucket(bucket_name)
                        blob = bucket.blob(blob_name)
                        transformed[key] = blob.generate_signed_url(
                            version="v4", expiration=timedelta(minutes=15), method="GET"
                        )
                    else:
                        transformed[key] = path_or_url
                except Exception as exc:
                    LOGGER.warning("Failed to sign GCS URL: %s. Error: %s", path_or_url, exc)
                    # Fallback to an authenticated browser download link.
                    # This relies on the user being logged into Google and having permission to view the object in the bucket.
                    parts = path_or_url.replace("gs://", "").split("/", 1)
                    if len(parts) == 2:
                        transformed[key] = f"https://storage.cloud.google.com/{parts[0]}/{parts[1]}"
                    else:
                        transformed[key] = path_or_url
            else:
                transformed[key] = path_or_url
        elif path_or_url.startswith("http"):
            transformed[key] = path_or_url
        else:
            # Assume local path; extract filename and build URL
            filename = Path(path_or_url).name
            url = str(request.url_for("download_account_list_artifact", filename=filename))
            if current_key:
                url = f"{url}?key={current_key}"
            transformed[key] = url
    return transformed


@router.post(
    "/extract",
    response_model=AccountListResult,
    summary="Extract financial account indicators from analyst data",
)
def extract_account_list(
    payload: AccountListRequest,
    request: Request,
    _: None = Depends(require_account_list_access),
    service: AccountListService = Depends(get_account_list_service),
    settings: Settings = Depends(get_settings),
) -> AccountListResult:
    """Execute the account-list workflow and return structured indicators."""

    max_top_k = settings.account_list.max_top_k
    if payload.top_k > max_top_k:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"top_k cannot exceed {max_top_k}",
        )
    actor = _resolve_actor(request)
    result = service.run(payload)
    LOGGER.info(
        "Account list API run %s by %s: indicators=%s warnings=%s artifacts=%s",
        result.request_id,
        actor,
        len(result.indicators),
        len(result.warnings),
        list(result.artifacts.values()) if result.artifacts else [],
    )

    try:
        log_account_list_run(actor=actor, source="api", result=result)
    except Exception:  # pragma: no cover - defensive path
        LOGGER.exception("Failed to write account list audit entry", extra={"request_id": result.request_id})

    # Transform local artifact paths to download URLs
    if result.artifacts:
        result = result.model_copy(update={"artifacts": _transform_artifacts(result.artifacts, request)})

    return result


@router.get(
    "/artifacts/{filename}",
    summary="Download an account list extraction artifact",
    operation_id="download_account_list_artifact",
)
def download_account_list_artifact(
    filename: str,
    _: None = Depends(require_account_list_access),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    """Stream a generated report artifact from local storage."""
    # Re-instantiate exporter logic to resolve base path safely
    # (Checking against configured directory prevents traversal)
    base_dir = settings.data_dir / "reports" / "account_list"
    target_path = (base_dir / filename).resolve()

    if not target_path.exists():
        raise HTTPException(status_code=404, detail="Artifact not found")

    # Ensure the resolved path is within the base directory
    if not str(target_path).startswith(str(base_dir.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")

    return FileResponse(
        path=target_path,
        media_type="application/octet-stream",
        filename=filename,
    )


def _parse_datetime(value: Any) -> datetime | None:
    from i4g.utils.datetime_parse import parse_datetime

    return parse_datetime(value, on_error="none")


def _parse_run_action(record: Dict[str, Any], request: Request) -> AccountListRunSummary | None:
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return None

    generated_at = _parse_datetime(payload.get("generated_at") or record.get("created_at"))
    if not generated_at:
        return None

    request_id = record.get("review_id") or payload.get("request_id")
    if not isinstance(request_id, str) or not request_id:
        return None

    actor = str(record.get("actor") or payload.get("actor") or "accounts_api")
    source = str(payload.get("source") or "api")

    indicator_count = int(payload.get("indicator_count") or 0)
    source_count = int(payload.get("source_count") or 0)
    raw_warnings = payload.get("warnings")
    warnings = raw_warnings if isinstance(raw_warnings, list) else []
    raw_artifacts = payload.get("artifacts")
    artifacts = raw_artifacts if isinstance(raw_artifacts, dict) else {}
    raw_categories = payload.get("categories")
    categories = raw_categories if isinstance(raw_categories, list) else []
    raw_metadata = payload.get("metadata")
    metadata = raw_metadata if isinstance(raw_metadata, dict) else {}

    # Transform artifacts
    transformed_artifacts = _transform_artifacts(dict(artifacts), request)

    return AccountListRunSummary(
        request_id=request_id,
        actor=actor,
        source=source,
        generated_at=generated_at,
        indicator_count=indicator_count,
        source_count=source_count,
        warnings=list(warnings),
        artifacts=transformed_artifacts,
        categories=list(categories),
        metadata=dict(metadata),
    )


@router.get(
    "/runs",
    response_model=AccountListRunResponse,
    summary="List recent account list runs",
)
def list_account_list_runs(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    _: None = Depends(require_account_list_access),
    store: ReviewStore = Depends(get_review_store),
) -> AccountListRunResponse:
    """Return recent account list audit entries for console surfaces."""

    actions = store.get_recent_actions(action=_AUDIT_ACTION, limit=limit)
    runs = []
    for action in actions:
        summary = _parse_run_action(action, request)
        if summary:
            runs.append(summary)
    return AccountListRunResponse(runs=runs, count=len(runs))
