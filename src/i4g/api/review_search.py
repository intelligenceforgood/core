"""Review search sub-router.

Endpoints under ``/reviews/search/*`` plus saved-search CRUD. Mounted
by the main ``review.py`` orchestrator.
"""

import logging
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError

from i4g.api.auth import require_token
from i4g.api.review_search_utils import (
    clean_text_value,
    coerce_entities,
    coerce_positive_int,
    coerce_string_list,
    coerce_time_range,
    first_value,
)
from i4g.api.review_deps import (
    SEARCH_AUDIT_REVIEW_ID,
    SETTINGS,
    get_campaign_service,
    get_hybrid_search_service,
    get_store,
)
from i4g.api.response_models import (
    AdvancedSearchResultsResponse,
    BulkTagResponse,
    EventListResponse,
    IdResponse,
    ItemListResponse,
    MutationResponse,
    PresetListResponse,
    SavedSearchExportResponse,
    SearchResultsResponse,
    SearchSchemaResponse,
)
from i4g.services.campaigns import CampaignService
from i4g.services.hybrid_search import HybridSearchQuery, HybridSearchService, QueryEntityFilter, QueryTimeRange
from i4g.store.review_store import ReviewStore

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class TimeRangeModel(BaseModel):
    start: datetime
    end: datetime


class EntityFilterModel(BaseModel):
    type: str
    value: str
    match_mode: Literal["exact", "prefix", "contains"] = "exact"


class HybridSearchRequest(BaseModel):
    text: str | None = None
    classifications: list[str] = Field(default_factory=list)
    datasets: list[str] = Field(default_factory=list)
    loss_buckets: list[str] = Field(default_factory=list)
    case_ids: list[str] = Field(default_factory=list)
    entities: list[EntityFilterModel] = Field(default_factory=list)
    time_range: TimeRangeModel | None = None
    limit: int | None = Field(default=None, ge=1, le=100)
    vector_limit: int | None = Field(default=None, ge=1, le=100)
    structured_limit: int | None = Field(default=None, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    saved_search_id: str | None = None
    saved_search_name: str | None = None
    saved_search_owner: str | None = None
    saved_search_tags: list[str] = Field(default_factory=list)


class SavedSearchRequest(BaseModel):
    name: str
    params: dict[str, Any]
    search_id: str | None = None
    favorite: bool | None = False
    tags: list[str] | None = None


class SavedSearchUpdate(BaseModel):
    name: str | None = None
    params: dict[str, Any] | None = None
    favorite: bool | None = None
    tags: list[str] | None = None


class SavedSearchCloneRequest(BaseModel):
    search_id: str


class SavedSearchImportRequest(BaseModel):
    name: str
    params: dict[str, Any]
    favorite: bool | None = False
    search_id: str | None = None
    tags: list[str] | None = None


class BulkTagUpdateRequest(BaseModel):
    search_ids: list[str]
    add: list[str] | None = None
    remove: list[str] | None = None
    replace: list[str] | None = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/search", summary="Search cases across structured/vector stores", response_model=SearchResultsResponse)
def search_cases(
    text: str | None = Query(None, description="Free-text search for semantic similarity"),
    classification: str | None = Query(None, description="Filter by classification label"),
    case_id: str | None = Query(None, description="Filter by exact case ID"),
    limit: int = Query(5, ge=1, le=50),
    vector_limit: int | None = Query(None, ge=1, le=50),
    structured_limit: int | None = Query(None, ge=1, le=50),
    offset: int = Query(0, ge=0),
    page_size: int | None = Query(None, ge=1, le=100, description="Maximum number of merged results to return"),
    search_service: HybridSearchService = Depends(get_hybrid_search_service),
    user: dict[str, Any] = Depends(require_token),
    store: ReviewStore = Depends(get_store),
) -> dict[str, Any]:
    """Combine semantic and structured search for analyst triage.

    Args:
        text: Free-text search query.
        classification: Filter by classification label.
        case_id: Filter by exact case ID.
        limit: Limit for individual search components (deprecated, use page_size).
        vector_limit: Specific limit for vector search.
        structured_limit: Specific limit for structured search.
        offset: Pagination offset.
        page_size: Maximum number of merged results to return.
        search_service: The hybrid search service.
        user: The authenticated user.
        store: The review store.

    Returns:
        A dictionary containing search results and diagnostics.
    """
    logger.info("search_cases: text=%r classification=%r offset=%d", text, classification, offset)
    payload = HybridSearchRequest(
        text=text,
        classifications=[classification] if classification else [],
        case_ids=[case_id] if case_id else [],
        limit=page_size or limit,
        vector_limit=vector_limit,
        structured_limit=structured_limit,
        offset=offset,
    )
    query = _build_hybrid_query_from_request(payload)
    query_result = search_service.search(query)
    results = query_result["results"]
    diagnostics = query_result.get("diagnostics")
    diag_counts = diagnostics.get("counts", {}) if isinstance(diagnostics, dict) else {}
    search_id = f"search:{uuid.uuid4()}"

    return {
        "results": results,
        "count": len(results),
        "offset": offset,
        "limit": page_size or len(results),
        "total": query_result["total"],
        "vector_hits": query_result.get("vector_hits"),
        "structured_hits": query_result.get("structured_hits"),
        "merged_results": diag_counts.get("merged_results"),
        "source_breakdown": diag_counts.get("source_breakdown"),
        "diagnostics": diagnostics,
        "search_id": search_id,
        "duration_ms": query_result.get("duration_ms"),
    }


@router.get("/search/history", summary="List recent search actions", response_model=EventListResponse)
def search_history(
    limit: int = Query(20, ge=1, le=200),
    store: ReviewStore = Depends(get_store),
    user=Depends(require_token),
):
    """Return recent search audit entries."""
    actions = store.get_recent_actions(action="search", limit=limit)
    return {"events": actions, "count": len(actions)}


@router.post("/search/query", summary="Execute advanced hybrid search with structured filters", response_model=AdvancedSearchResultsResponse)
def search_cases_advanced(
    payload: HybridSearchRequest,
    search_service: HybridSearchService = Depends(get_hybrid_search_service),
    user=Depends(require_token),
    store: ReviewStore = Depends(get_store),
):
    """Execute advanced hybrid search with structured filters."""
    logger.info("search_cases_advanced: text=%r filters=%d offset=%d", payload.text, len(payload.classifications), payload.offset)
    query = _build_hybrid_query_from_request(payload)
    query_result = search_service.search(query)
    search_id = f"search:{uuid.uuid4()}"
    diagnostics = query_result.get("diagnostics")
    diag_counts = diagnostics.get("counts", {}) if isinstance(diagnostics, dict) else {}
    saved_search_descriptor = _build_saved_search_descriptor(payload)
    log_payload: dict[str, Any] = {
        "search_id": search_id,
        "request": payload.model_dump(),
        "results_count": query_result["count"],
        "total": query_result["total"],
        "vector_hits": query_result.get("vector_hits"),
        "structured_hits": query_result.get("structured_hits"),
        "merged_results": diag_counts.get("merged_results"),
        "source_breakdown": diag_counts.get("source_breakdown"),
        "diagnostics": diagnostics,
    }
    if saved_search_descriptor:
        log_payload["saved_search"] = saved_search_descriptor
        if saved_search_descriptor.get("id"):
            log_payload["saved_search_id"] = saved_search_descriptor["id"]
        if saved_search_descriptor.get("name"):
            log_payload["saved_search_name"] = saved_search_descriptor["name"]
        if saved_search_descriptor.get("owner"):
            log_payload["saved_search_owner"] = saved_search_descriptor["owner"]
        if saved_search_descriptor.get("tags"):
            log_payload["saved_search_tags"] = saved_search_descriptor["tags"]

    store.ensure_placeholder_review(SEARCH_AUDIT_REVIEW_ID, case_id="system:search-audit")
    store.log_action(
        review_id=SEARCH_AUDIT_REVIEW_ID,
        actor=user.get("username"),
        action="search",
        payload=log_payload,
    )

    return {**query_result, "search_id": search_id}


@router.get("/search/schema", summary="Describe hybrid search filters for clients", response_model=SearchSchemaResponse)
def get_search_schema(
    search_service: HybridSearchService = Depends(get_hybrid_search_service),
    campaign_service: CampaignService = Depends(get_campaign_service),
    user=Depends(require_token),
):
    """Describe hybrid search filters for clients."""
    schema = search_service.schema()

    # Enrich schema with active campaigns
    try:
        campaigns = campaign_service.list_active_campaigns()
        if campaigns:
            schema["classifications"] = sorted([c["name"] for c in campaigns])
            schema["campaigns"] = campaigns
    except Exception:
        logger.debug("Failed to enrich search schema with campaigns", exc_info=True)

    return schema


@router.post("/search/saved", summary="Create or update a saved search", response_model=IdResponse)
def save_search(
    payload: SavedSearchRequest,
    store: ReviewStore = Depends(get_store),
    user=Depends(require_token),
):
    """Create or update a saved search."""
    logger.info("save_search: name=%r user=%s", payload.name, user.get("username"))
    params = _normalize_saved_search_params(payload.params)
    try:
        search_id = store.upsert_saved_search(
            payload.name,
            params,
            owner=user.get("username"),
            search_id=payload.search_id,
            favorite=payload.favorite or False,
            tags=payload.tags or [],
        )
    except ValueError as exc:
        msg = str(exc)
        if msg.startswith("duplicate_saved_search"):
            owner = "shared"
            if ":" in msg:
                owner_val = msg.split(":", 1)[1]
                owner = owner_val or "shared"
            raise HTTPException(
                status_code=409,
                detail=f"Saved search name already exists (owner={owner})",
            )
        raise
    return {"search_id": search_id}


@router.get("/search/saved", summary="List saved searches", response_model=ItemListResponse)
def list_saved_searches(
    limit: int = Query(50, ge=1, le=200),
    owner_only: bool = Query(False, description="If true, only return searches owned by the caller"),
    store: ReviewStore = Depends(get_store),
    user=Depends(require_token),
):
    """List saved searches."""
    owner = user.get("username") if owner_only else None
    raw_items = store.list_saved_searches(owner=owner, limit=limit)
    items = []
    for entry in raw_items:
        params = entry.get("params") if isinstance(entry, dict) else None
        if isinstance(entry, dict):
            normalized = dict(entry)
            normalized["params"] = _normalize_saved_search_params(params or {}, strict=False)
            items.append(normalized)
        else:
            items.append(entry)
    return {"items": items, "count": len(items)}


@router.get("/search/tag-presets", summary="List tag presets derived from saved searches", response_model=PresetListResponse)
def list_tag_presets(
    limit: int = Query(50, ge=1, le=200),
    owner_only: bool = Query(False, description="If true, only return tag presets owned by the caller"),
    include_shared: bool = Query(True, description="Include shared presets when listing"),
    store: ReviewStore = Depends(get_store),
    user=Depends(require_token),
):
    """List tag presets derived from saved searches."""
    owner = user.get("username") if owner_only else None
    effective_owner = None if (include_shared and not owner_only) else owner
    presets = store.list_tag_presets(owner=effective_owner, limit=limit)
    return {"presets": presets, "count": len(presets)}


@router.post("/search/saved/bulk-tags", summary="Bulk update tags for saved searches", response_model=BulkTagResponse)
def bulk_update_tags(
    payload: BulkTagUpdateRequest,
    store: ReviewStore = Depends(get_store),
    user=Depends(require_token),
):
    """Bulk update tags for saved searches."""
    if not payload.search_ids:
        raise HTTPException(status_code=400, detail="No search IDs provided")
    updated = store.bulk_update_tags(
        payload.search_ids,
        add=payload.add,
        remove=payload.remove,
        replace=payload.replace,
    )
    return {"updated": updated}


@router.delete("/search/saved/{search_id}", summary="Delete a saved search", response_model=MutationResponse)
def delete_saved_search(
    search_id: str,
    store: ReviewStore = Depends(get_store),
    user=Depends(require_token),
):
    """Delete a saved search."""
    logger.info("delete_saved_search: search_id=%s user=%s", search_id, user.get("username"))
    deleted = store.delete_saved_search(search_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Saved search not found")
    return {"deleted": True, "search_id": search_id}


@router.patch("/search/saved/{search_id}", summary="Update a saved search", response_model=MutationResponse)
def patch_saved_search(
    search_id: str,
    payload: SavedSearchUpdate,
    store: ReviewStore = Depends(get_store),
    user=Depends(require_token),
):
    """Update a saved search."""
    logger.info("patch_saved_search: search_id=%s user=%s", search_id, user.get("username"))
    params = _normalize_saved_search_params(payload.params) if payload.params is not None else None
    try:
        updated = store.update_saved_search(
            search_id,
            name=payload.name,
            params=params,
            favorite=payload.favorite,
            tags=payload.tags,
        )
    except ValueError as exc:
        msg = str(exc)
        if msg.startswith("duplicate_saved_search"):
            owner = "shared"
            if ":" in msg:
                owner_val = msg.split(":", 1)[1]
                owner = owner_val or "shared"
            raise HTTPException(
                status_code=409,
                detail=f"Saved search name already exists (owner={owner})",
            )
        raise
    if not updated:
        raise HTTPException(status_code=404, detail="Saved search not found or nothing to update")
    return {"updated": True, "search_id": search_id}


@router.post("/search/saved/{search_id}/share", summary="Promote a saved search to shared scope", response_model=IdResponse)
def share_saved_search(
    search_id: str,
    store: ReviewStore = Depends(get_store),
    user=Depends(require_token),
):
    """Promote a saved search to shared scope."""
    try:
        shared_id = store.clone_saved_search(search_id, target_owner=None)
    except ValueError as exc:
        msg = str(exc)
        if msg == "saved_search_not_found":
            raise HTTPException(status_code=404, detail="Saved search not found")
        if msg.startswith("duplicate_saved_search"):
            owner = "shared"
            if ":" in msg:
                owner_val = msg.split(":", 1)[1]
                owner = owner_val or "shared"
            raise HTTPException(
                status_code=409,
                detail=f"Shared search name already exists (owner={owner})",
            )
        raise
    return {"search_id": shared_id}


@router.get("/search/saved/{search_id}/export", summary="Export a saved search configuration", response_model=SavedSearchExportResponse)
def export_saved_search(
    search_id: str,
    store: ReviewStore = Depends(get_store),
    user=Depends(require_token),
):
    """Export a saved search configuration."""
    record = store.get_saved_search(search_id)
    if not record:
        raise HTTPException(status_code=404, detail="Saved search not found")
    record["params"] = _normalize_saved_search_params(record.get("params") or {}, strict=False)
    return record


@router.post("/search/saved/import", summary="Import a saved search definition", response_model=IdResponse)
def import_saved_search(
    payload: SavedSearchImportRequest,
    store: ReviewStore = Depends(get_store),
    user=Depends(require_token),
):
    """Import a saved search definition."""
    logger.info("import_saved_search: name=%r user=%s", payload.name, user.get("username"))
    record = payload.model_dump()
    record["params"] = _normalize_saved_search_params(record["params"])
    try:
        search_id = store.import_saved_search(record, owner=user.get("username"))
    except ValueError as exc:
        msg = str(exc)
        if msg.startswith("duplicate_saved_search"):
            owner = "shared"
            if ":" in msg:
                owner_val = msg.split(":", 1)[1]
                owner = owner_val or "shared"
            raise HTTPException(
                status_code=409,
                detail=f"Saved search name already exists (owner={owner})",
            )
        raise HTTPException(status_code=400, detail="Invalid saved search payload")
    return {"search_id": search_id}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_hybrid_query_from_request(payload: HybridSearchRequest) -> HybridSearchQuery:
    """Convert API payload into the service query dataclass."""
    entities = [
        QueryEntityFilter(type=entity.type, value=entity.value, match_mode=entity.match_mode)
        for entity in payload.entities
    ]
    time_range = None
    if payload.time_range:
        if payload.time_range.end < payload.time_range.start:
            raise HTTPException(status_code=400, detail="time_range.end must be after start")
        time_range = QueryTimeRange(start=payload.time_range.start, end=payload.time_range.end)

    return HybridSearchQuery(
        text=payload.text,
        classifications=payload.classifications,
        datasets=payload.datasets,
        loss_buckets=payload.loss_buckets,
        case_ids=payload.case_ids,
        entities=entities,
        time_range=time_range,
        limit=payload.limit,
        vector_limit=payload.vector_limit,
        structured_limit=payload.structured_limit,
        offset=payload.offset,
    )


def _build_saved_search_descriptor(payload: HybridSearchRequest) -> dict[str, Any] | None:
    """Build a saved-search descriptor from the request payload."""
    tags: list[str] = []
    for tag in payload.saved_search_tags or []:
        text = clean_text_value(tag)
        if text:
            tags.append(text)

    descriptor: dict[str, Any] = {
        "id": clean_text_value(payload.saved_search_id),
        "name": clean_text_value(payload.saved_search_name),
        "owner": clean_text_value(payload.saved_search_owner),
        "tags": tags,
    }

    if descriptor["id"] or descriptor["name"] or descriptor["owner"] or descriptor["tags"]:
        return descriptor
    return None


def _normalize_saved_search_params(params: dict[str, Any], *, strict: bool = True) -> dict[str, Any]:
    """Normalise saved-search params into a canonical form."""
    if not isinstance(params, dict):
        if strict:
            raise HTTPException(status_code=400, detail="Saved search params must be an object")
        return _apply_saved_search_schema_version({})

    try:
        request_model = _build_saved_search_request(params)
    except HTTPException:
        if strict:
            raise
        return _apply_saved_search_schema_version(dict(params))
    except ValidationError as exc:
        if strict:
            raise HTTPException(status_code=400, detail=f"Invalid saved search params: {exc.errors()[0]['msg']}")
        return _apply_saved_search_schema_version(dict(params))

    normalized = request_model.model_dump(exclude_none=True)
    normalized = _post_process_saved_search_params(normalized, params)
    normalized = _apply_saved_search_schema_version(normalized, provided=params.get("schema_version"))
    return normalized


def _saved_search_schema_version_default() -> str | None:
    """Return the configured default schema version for saved searches."""
    configured = (SETTINGS.search.saved_search.schema_version or "").strip()
    if configured:
        return configured
    fallback = (SETTINGS.search.saved_search.migration_tag or "").strip()
    return fallback or None


def _build_saved_search_request(params: dict[str, Any]) -> HybridSearchRequest:
    """Construct a ``HybridSearchRequest`` from raw saved-search params."""
    payload: dict[str, Any] = {}

    payload["text"] = clean_text_value(params.get("text"))
    payload["classifications"] = coerce_string_list(params.get("classifications"), params.get("classification"))
    payload["datasets"] = coerce_string_list(params.get("datasets"))
    payload["loss_buckets"] = coerce_string_list(params.get("loss_buckets"))
    payload["case_ids"] = coerce_string_list(params.get("case_ids"), params.get("case_id"))
    payload["entities"] = coerce_entities(params.get("entities"))

    time_range = coerce_time_range(params.get("time_range"))
    if time_range:
        payload["time_range"] = time_range

    limit = coerce_positive_int(params.get("limit"), max_value=100)
    if not limit:
        limit = coerce_positive_int(params.get("page_size"), max_value=100)
    if not limit:
        limit = min(SETTINGS.search.default_limit, 100)
    payload["limit"] = limit
    payload["vector_limit"] = coerce_positive_int(params.get("vector_limit"), max_value=100) or limit
    payload["structured_limit"] = coerce_positive_int(params.get("structured_limit"), max_value=100) or limit
    payload["offset"] = coerce_positive_int(params.get("offset"), allow_zero=True, max_value=10_000) or 0

    return HybridSearchRequest(**payload)


def _post_process_saved_search_params(normalized: dict[str, Any], original: dict[str, Any]) -> dict[str, Any]:
    """Enrich normalised params with legacy convenience fields."""
    result = dict(normalized)

    # Preserve legacy scalar fields for older clients
    classification_value = first_value(result.get("classifications"), original.get("classification"))
    if classification_value:
        result["classification"] = classification_value

    case_value = first_value(result.get("case_ids"), original.get("case_id"))
    if case_value:
        result["case_id"] = case_value

    # Align limit/page size defaults
    provided_page_size = coerce_positive_int(original.get("page_size"), max_value=100)
    if provided_page_size:
        result["page_size"] = provided_page_size
        result.setdefault("limit", provided_page_size)
    else:
        result.setdefault("page_size", result.get("limit"))

    result["vector_limit"] = result.get("vector_limit") or result.get("limit")
    result["structured_limit"] = result.get("structured_limit") or result.get("limit")

    # Ensure lists exist for downstream UI expectations
    for field in ("classifications", "datasets", "loss_buckets", "case_ids", "entities"):
        result[field] = result.get(field) or []

    if result.get("time_range"):
        tr = result["time_range"]
        result["time_range"] = {
            "start": tr["start"].isoformat() if isinstance(tr["start"], datetime) else tr["start"],
            "end": tr["end"].isoformat() if isinstance(tr["end"], datetime) else tr["end"],
        }

    return result


def _apply_saved_search_schema_version(params: dict[str, Any], provided: Any | None = None) -> dict[str, Any]:
    """Stamp the schema-version field on saved-search params."""
    normalized = dict(params)
    candidates = []
    if provided is not None:
        candidates.append(provided)
    if "schema_version" in normalized:
        candidates.append(normalized["schema_version"])
    version_value = ""
    for candidate in candidates:
        if isinstance(candidate, str):
            version_value = candidate.strip()
        elif candidate is not None:
            version_value = str(candidate).strip()
        if version_value:
            break

    if version_value:
        normalized["schema_version"] = version_value
        return normalized

    fallback = _saved_search_schema_version_default()
    if fallback:
        normalized["schema_version"] = fallback
    else:
        normalized.pop("schema_version", None)
    return normalized


