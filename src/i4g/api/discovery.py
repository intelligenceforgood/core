"""FastAPI router exposing Discovery search."""

from __future__ import annotations

import base64
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query

from i4g.services.discovery import DiscoverySearchParams, get_default_discovery_params, run_discovery_search
from i4g.services.hybrid_search import HybridSearchQuery, HybridSearchService
from i4g.settings import get_settings

router = APIRouter(prefix="/discovery", tags=["discovery"])
SETTINGS = get_settings()


def _mock_discovery_response(query: str) -> Dict[str, Any]:
    """Return a lightweight mock payload to keep the UI working locally."""

    base_summary = f'Mock hit for "{query}"' if query else "Mock Discovery result"
    template = {
        "summary": base_summary,
        "label": "demo",
        "tags": ["demo", "vertex"],
        "source": "mock",
        "index_type": "demo-index",
        "struct": {"summary": base_summary},
        "rank_signals": {"semanticSimilarityScore": 0.91},
        "raw": {"message": "Mock result"},
    }
    results: List[Dict[str, Any]] = []
    for offset in range(3):
        results.append(
            {
                **template,
                "document_id": f"mock-{offset + 1}",
                "document_name": f"mock-document-{offset + 1}",
                "tags": ["demo", "vertex", f"sample-{offset + 1}"],
                "rank": offset + 1,
            }
        )

    return {"results": results, "total_size": len(results), "next_page_token": None}


def _local_discovery_search(query: str, limit: int, offset: int = 0) -> Dict[str, Any]:
    """Use local HybridSearchService to simulate Discovery results."""
    try:
        service = HybridSearchService()
        search_query = HybridSearchQuery(text=query, limit=limit, offset=offset)
        result = service.search(search_query)

        mapped_results = []
        for i, item in enumerate(result["results"]):
            doc_id = item.get("case_id") or f"doc-{i}"
            metadata = item.get("metadata") or {}
            vector = item.get("vector") or {}
            record = item.get("record") or {}

            # Try to find a title/summary
            title = metadata.get("title") or metadata.get("case_id") or f"Result {doc_id}"

            # Resolve snippet from various possible locations
            snippet = (
                metadata.get("summary")
                or metadata.get("text")
                or record.get("text")
                or vector.get("text")
                or vector.get("document")
                or "No snippet available"
            )

            mapped_results.append(
                {
                    "document_id": doc_id,
                    "document_name": title,
                    "struct": {"title": title, "summary": snippet, **metadata},
                    "rank_signals": {"semanticSimilarityScore": item.get("merged_score", 0.0)},
                    "rank": offset + i + 1,
                }
            )

        # Generate next page token if we have a full page
        next_page_token = None
        if len(mapped_results) >= limit:
            next_offset = offset + limit
            next_page_token = base64.urlsafe_b64encode(str(next_offset).encode()).decode()

        # Estimate total size to be at least the next page if we have a token
        total_size = result["total"]
        if next_page_token and total_size <= (offset + limit):
            total_size = offset + limit + 1

        return {"results": mapped_results, "total_size": total_size, "next_page_token": next_page_token}
    except Exception:
        # Fallback to static mock if local search fails
        return _mock_discovery_response(query)


@router.get("/search")
def discovery_search(
    query: str = Query(..., min_length=1, description="User-provided Discovery query string."),
    page_size: int = Query(10, ge=1, le=50, description="Number of results to return."),
    page_token: str | None = Query(None, description="Page token for pagination."),
    offset: int = Query(0, description="Offset (alternative to page token)."),
    project: str | None = Query(None, description="Optional override for the Discovery project."),
    location: str | None = Query(None, description="Optional override for the Discovery location."),
    data_store_id: str | None = Query(None, description="Optional override for the data store ID."),
    serving_config_id: str | None = Query(None, description="Optional override for the serving config."),
    filter_expression: str | None = Query(None, alias="filter", description="Discovery filter expression."),
    boost_json: str | None = Query(None, alias="boost", description="JSON BoostSpec payload."),
):
    """Execute a Discovery search using shared i4g defaults."""

    # Resolve offset from page_token if provided
    effective_offset = offset
    if page_token:
        try:
            decoded = base64.urlsafe_b64decode(page_token).decode()
            effective_offset = int(decoded)
        except Exception:
            pass  # Ignore invalid tokens

    try:
        params = get_default_discovery_params(
            query=query, page_size=page_size, page_token=page_token, offset=effective_offset
        )
    except RuntimeError as exc:  # pragma: no cover - configuration errors surface to clients
        if SETTINGS.is_local:
            return _local_discovery_search(query, page_size, effective_offset)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if project:
        params.project = project
    if location:
        params.location = location
    if data_store_id:
        params.data_store_id = data_store_id
    if serving_config_id:
        params.serving_config_id = serving_config_id
    if filter_expression:
        params.filter_expression = filter_expression
    if boost_json:
        params.boost_json = boost_json

    try:
        return run_discovery_search(params)
    except RuntimeError as exc:  # pragma: no cover - surfaces backend errors
        if SETTINGS.is_local:
            return _local_discovery_search(query, page_size, effective_offset)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


__all__ = ["router"]
