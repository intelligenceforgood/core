"""FastAPI router exposing the PhishDestroy domain-discoveries surface."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field

from i4g.api.auth import require_token
from i4g.api.camel import CamelModel
from i4g.services.factories import build_domain_discovery_store
from i4g.store.domain_discovery_store import DomainDiscoveryStore
from i4g.worker.jobs.merklemap_tail import enqueue_passive_scan_for_domain

router = APIRouter(
    prefix="/discoveries",
    tags=["discoveries"],
    dependencies=[Depends(require_token)],
)


class DiscoveryRow(CamelModel):
    discovery_id: str
    domain: str
    seen_at: datetime
    source: str
    filter_match: bool
    filter_reason: str | None = None
    enqueued_scan_id: str | None = None
    dismissed_at: datetime | None = None
    dismiss_reason: str | None = None


class DiscoveryList(CamelModel):
    items: list[DiscoveryRow]
    total: int
    limit: int
    offset: int


class DismissRequest(CamelModel):
    reason: str | None = Field(default=None, max_length=500)


class EnqueueResponse(CamelModel):
    discovery_id: str
    enqueued_scan_id: str


def _get_row_or_404(discovery_id: str, store: DomainDiscoveryStore) -> dict[str, Any]:
    """Fetch a discovery row by id or raise 404."""
    row = store.get(discovery_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Discovery not found")
    return row


@router.get("", response_model=DiscoveryList)
def list_discoveries(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    since: datetime | None = Query(default=None),
) -> DiscoveryList:
    """List filter-matched, non-dismissed domain discoveries (paginated)."""
    store = build_domain_discovery_store()
    items = store.list_recent_matches(limit=limit, offset=offset, since=since)
    total = store.count_recent_matches(since=since)
    return DiscoveryList(
        items=[DiscoveryRow(**r) for r in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/{discovery_id}/enqueue", response_model=EnqueueResponse)
def enqueue_discovery(discovery_id: str) -> EnqueueResponse:
    """Enqueue a discovery for passive SSI scan."""
    store = build_domain_discovery_store()
    row = _get_row_or_404(discovery_id, store)

    if row.get("dismissed_at") is not None:
        raise HTTPException(status_code=409, detail="Discovery already dismissed")
    if row.get("enqueued_scan_id") is not None:
        raise HTTPException(status_code=409, detail="Discovery already enqueued")

    scan_id = enqueue_passive_scan_for_domain(
        url=row["domain"],
        discovery_id=discovery_id,
        store=store,
    )
    if scan_id is None:
        raise HTTPException(status_code=502, detail="SSI service unavailable")

    store.mark_enqueued(discovery_id, scan_id)
    return EnqueueResponse(discovery_id=discovery_id, enqueued_scan_id=scan_id)


@router.post("/{discovery_id}/dismiss", response_model=DiscoveryRow)
def dismiss_discovery(discovery_id: str, body: DismissRequest) -> DiscoveryRow:
    """Soft-dismiss a discovery without enqueueing it."""
    store = build_domain_discovery_store()
    row = _get_row_or_404(discovery_id, store)

    if row.get("dismissed_at") is not None:
        raise HTTPException(status_code=409, detail="Discovery already dismissed")

    updated = store.dismiss(discovery_id, body.reason)
    if updated is None:
        raise HTTPException(status_code=404, detail="Discovery not found")
    return DiscoveryRow(**updated)
