"""Partner indicator feed API router (S6-09, S6-10, S6-11).

Provides a machine-readable, TLP-tagged, paginated indicator feed for
partner organizations. Partners authenticate via dedicated API keys
(separate from analyst console auth).

Rate limiting and audit logging are applied per-key.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from i4g.api.camel import CamelModel
from i4g.services.export_adapters import CsvAdapter, StixAdapter
from i4g.services.factories import build_analytics_store
from i4g.settings import get_settings
from i4g.store.sql import partner_api_keys, partner_feed_audit
from i4g.store.sql import session_factory as build_sql_session_factory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/feeds", tags=["partner-feeds"])

# In-memory rate limit tracking (per key_id → list of timestamps)
_rate_windows: dict[str, list[float]] = defaultdict(list)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class FeedIndicator(CamelModel):
    """Single indicator in the partner feed."""

    indicator_id: str
    category: str
    indicator_type: str = ""
    indicator_value: str
    case_count: int = 0
    loss_sum: float = 0.0
    max_risk_score: float = 0.0
    first_seen_at: str | None = None
    last_seen_at: str | None = None
    tlp: str = "TLP:AMBER"


class FeedResponse(CamelModel):
    """Paginated indicator feed response."""

    items: list[FeedIndicator]
    total: int
    page: int
    page_size: int
    has_more: bool


# ---------------------------------------------------------------------------
# Partner API key authentication
# ---------------------------------------------------------------------------


def _hash_key(raw_key: str) -> str:
    """Compute SHA-256 hash of an API key.

    Args:
        raw_key: The raw API key string.

    Returns:
        Hex-encoded SHA-256 digest.
    """
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _authenticate_partner(request: Request, x_api_key: str = Header(..., alias="X-Partner-API-Key")) -> dict[str, Any]:
    """Validate partner API key and return key metadata.

    Args:
        request: The incoming request (for IP logging).
        x_api_key: The partner API key from the header.

    Returns:
        Key metadata dict from the database.

    Raises:
        HTTPException: 401 if key is invalid, 403 if expired or inactive.
    """
    settings = get_settings()
    if not getattr(getattr(settings, "partner_feed", None), "enabled", False):
        raise HTTPException(status_code=403, detail="Partner feed API is disabled")

    key_hash = _hash_key(x_api_key)
    sf = build_sql_session_factory()

    with sf() as session:
        row = session.execute(sa.select(partner_api_keys).where(partner_api_keys.c.key_hash == key_hash)).fetchone()

        if not row:
            raise HTTPException(status_code=401, detail="Invalid API key")

        if not row.is_active:
            raise HTTPException(status_code=403, detail="API key deactivated")

        if row.expires_at and row.expires_at < datetime.now(UTC):
            raise HTTPException(status_code=403, detail="API key expired")

        # Update last_used_at
        session.execute(
            sa.update(partner_api_keys)
            .where(partner_api_keys.c.key_id == row.key_id)
            .values(last_used_at=datetime.now(UTC))
        )
        session.commit()

    return {
        "key_id": row.key_id,
        "partner_name": row.partner_name,
        "scopes": row.scopes,
        "rate_limit_per_minute": row.rate_limit_per_minute,
    }


def _check_rate_limit(key_meta: dict[str, Any]) -> None:
    """Enforce per-key rate limiting.

    Args:
        key_meta: Partner key metadata (must include key_id and rate_limit_per_minute).

    Raises:
        HTTPException: 429 if rate limit is exceeded.
    """
    key_id = key_meta["key_id"]
    limit = key_meta.get("rate_limit_per_minute", 60)
    now = time.monotonic()
    window = 60.0

    # Prune old entries
    _rate_windows[key_id] = [t for t in _rate_windows[key_id] if now - t < window]

    if len(_rate_windows[key_id]) >= limit:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    _rate_windows[key_id].append(now)


def _log_feed_access(
    key_meta: dict[str, Any],
    *,
    endpoint: str,
    method: str,
    query_params: dict[str, Any] | None,
    result_count: int,
    response_code: int,
    ip_address: str | None,
) -> None:
    """Write an audit log entry for a partner feed access.

    Args:
        key_meta: Partner key metadata.
        endpoint: The endpoint path.
        method: HTTP method.
        query_params: Query parameters.
        result_count: Number of results returned.
        response_code: HTTP response code.
        ip_address: Client IP address.
    """
    try:
        sf = build_sql_session_factory()
        with sf() as session:
            session.execute(
                partner_feed_audit.insert().values(
                    audit_id=str(uuid.uuid4()),
                    key_id=key_meta["key_id"],
                    partner_name=key_meta["partner_name"],
                    endpoint=endpoint,
                    method=method,
                    query_params=query_params,
                    result_count=result_count,
                    response_code=response_code,
                    ip_address=ip_address,
                    created_at=datetime.now(UTC),
                )
            )
            session.commit()
    except Exception:
        logger.warning("Failed to log feed access audit", exc_info=True)


# ---------------------------------------------------------------------------
# Feed endpoints
# ---------------------------------------------------------------------------


@router.get("/indicators", response_model=FeedResponse)
def get_indicator_feed(
    request: Request,
    category: str | None = Query(None, description="Filter by indicator category"),
    min_risk_score: float | None = Query(None, ge=0, le=100, description="Minimum risk score"),
    since: str | None = Query(None, description="ISO-8601 date; only indicators updated after this date"),
    tlp: str = Query("TLP:AMBER", description="TLP level filter"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int | None = Query(None, ge=1, description="Items per page"),
    fmt: str = Query("json", description="Response format: json, csv, stix"),
    key_meta: dict[str, Any] = Depends(_authenticate_partner),
) -> Any:
    """Paginated indicator feed for partner consumption.

    Returns indicators in JSON, CSV, or STIX 2.1 format, filtered by
    category, risk score, and recency.

    Args:
        request: Incoming HTTP request.
        category: Optional indicator category filter.
        min_risk_score: Minimum risk score threshold.
        since: Return only indicators updated after this ISO-8601 date.
        tlp: TLP classification filter.
        page: Page number (1-indexed).
        page_size: Items per page (defaults to partner_feed.default_page_size).
        fmt: Output format (json, csv, stix).
        key_meta: Authenticated partner key metadata.

    Returns:
        Paginated indicator data in the requested format.
    """
    _check_rate_limit(key_meta)

    settings = get_settings()
    feed_settings = settings.partner_feed
    effective_page_size = min(page_size or feed_settings.default_page_size, feed_settings.max_page_size)
    offset = (page - 1) * effective_page_size

    store = build_analytics_store()
    items = store.list_indicator_stats(
        category=category,
        limit=effective_page_size,
        offset=offset,
    )
    total = store.count_indicator_stats(category=category)

    # Apply post-query filters
    if min_risk_score is not None:
        items = [i for i in items if float(i.get("max_risk_score", 0)) >= min_risk_score]
    if since:
        items = [i for i in items if (i.get("updated_at") or i.get("last_seen_at", "")) >= since]

    feed_items = []
    for item in items:
        feed_items.append(
            FeedIndicator(
                indicator_id=f"{item.get('category', '')}:{item.get('item', '')}:{item.get('number', '')}",
                category=item.get("category", ""),
                indicator_type=item.get("item", ""),
                indicator_value=item.get("number", ""),
                case_count=int(item.get("case_count", 0)),
                loss_sum=float(item.get("loss_sum", 0)),
                max_risk_score=float(item.get("max_risk_score", 0)),
                first_seen_at=str(item.get("first_seen_at", "")) if item.get("first_seen_at") else None,
                last_seen_at=str(item.get("last_seen_at", "")) if item.get("last_seen_at") else None,
                tlp=tlp,
            )
        )

    client_ip = request.client.host if request.client else None

    # Audit log
    _log_feed_access(
        key_meta,
        endpoint="/feeds/indicators",
        method="GET",
        query_params={"category": category, "min_risk_score": min_risk_score, "since": since, "tlp": tlp},
        result_count=len(feed_items),
        response_code=200,
        ip_address=client_ip,
    )

    # Alternative format responses
    if fmt == "csv":
        from fastapi.responses import Response

        adapter = CsvAdapter()
        data = adapter.serialize([fi.model_dump() for fi in feed_items])
        return Response(content=data, media_type=adapter.content_type)

    if fmt == "stix":
        from fastapi.responses import JSONResponse

        adapter = StixAdapter()
        rows = [{"category": fi.category, "item": fi.indicator_type, "number": fi.indicator_value} for fi in feed_items]
        data = adapter.serialize(rows)
        return JSONResponse(content={"stix_bundle": data.decode("utf-8")}, media_type="application/json")

    return FeedResponse(
        items=feed_items,
        total=total,
        page=page,
        page_size=effective_page_size,
        has_more=(offset + effective_page_size) < total,
    )
