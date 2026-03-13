"""Intelligence API router — Entity Explorer, Indicator Registry, Dashboard widgets.

Provides endpoints for browsing pre-computed entity and indicator stats,
fetching dashboard widget data, entity sparklines, and entity neighbor graphs.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field

from i4g.api.auth import require_token
from i4g.api.camel import CamelModel
from i4g.api.roles import Role, has_role
from i4g.services.factories import build_analytics_store, build_threat_campaign_store
from i4g.store.analytics_store import AnalyticsStore
from i4g.store.threat_campaign_store import ThreatCampaignStore

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/intelligence",
    tags=["intelligence"],
    dependencies=[Depends(require_token)],
)


# ---------------------------------------------------------------------------
# Dependency factories
# ---------------------------------------------------------------------------


def get_analytics_store() -> AnalyticsStore:
    """Return an AnalyticsStore instance."""
    return build_analytics_store()


def get_campaign_store() -> ThreatCampaignStore:
    """Return a ThreatCampaignStore instance."""
    return build_threat_campaign_store()


def _is_researcher(user: dict[str, str]) -> bool:
    """Return True if the user has only researcher-level access."""
    return user.get("role") == Role.RESEARCHER and not has_role(user.get("role", ""), Role.USER)


def _map_indicator_fields(item: dict[str, Any]) -> dict[str, Any]:
    """Map DB column ``number`` to API field ``indicator_value``."""
    mapped = dict(item)
    if "number" in mapped:
        mapped["indicator_value"] = mapped.pop("number")
    return mapped


def _anonymize_entity(item: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of entity stats with PII redacted for researcher role."""
    redacted = dict(item)
    val = redacted.get("canonical_value", "")
    if len(val) > 4:
        redacted["canonical_value"] = "***" + val[-4:]
    else:
        redacted["canonical_value"] = "****"
    return redacted


def _anonymize_indicator(item: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of indicator stats with value redacted for researcher role."""
    redacted = dict(item)
    val = redacted.get("number", "")
    if len(val) > 4:
        redacted["number"] = "***" + val[-4:]
    else:
        redacted["number"] = "****"
    return redacted


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class EntityStatResponse(CamelModel):
    """Pre-computed entity statistics."""

    entity_type: str
    canonical_value: str
    case_count: int
    victim_count: int = 0
    loss_sum: float = 0.0
    loss_currency: str = "USD"
    max_risk_score: float = 0.0
    avg_risk_score: float = 0.0
    first_seen_at: str | None = None
    last_seen_at: str | None = None
    status: str = "active"
    campaign_ids: list[str] | None = None
    top_classifications: Any | None = None
    ecx_submitted: bool | None = None
    ecx_hit: bool | None = None
    purge_status: str | None = None
    updated_at: str | None = None


class EntityDetailResponse(EntityStatResponse):
    """Entity stats with campaign linkage."""

    campaigns: list[dict[str, str]] = Field(default_factory=list)


class IndicatorStatResponse(CamelModel):
    """Pre-computed indicator statistics."""

    indicator_id: str
    indicator_value: str
    category: str
    item: str | None = None
    type: str = ""
    case_count: int = 0
    loss_sum: float = 0.0
    max_risk_score: float = 0.0
    first_seen_at: str | None = None
    last_seen_at: str | None = None
    ecx_status: str | None = None
    updated_at: str | None = None


class EntityListResponse(CamelModel):
    """Paginated entity stats list."""

    items: list[EntityStatResponse]
    count: int
    limit: int
    offset: int


class IndicatorListResponse(CamelModel):
    """Paginated indicator stats list."""

    items: list[IndicatorStatResponse]
    count: int
    limit: int
    offset: int


class ActivityPoint(CamelModel):
    """Single data point in an entity activity sparkline."""

    week: str
    case_count: int


class NeighborNode(CamelModel):
    """Node in a mini neighbor graph."""

    id: str
    label: str
    entity_type: str
    case_count: int = 0


class NeighborEdge(CamelModel):
    """Edge in a mini neighbor graph."""

    source: str
    target: str
    weight: int = 1
    edge_type: str = "co-occurrence"


class NeighborGraphResponse(CamelModel):
    """1-hop co-occurrence graph around an entity."""

    seed: str
    nodes: list[NeighborNode]
    edges: list[NeighborEdge]


class DashboardWidgetsResponse(CamelModel):
    """Intelligence dashboard widget data."""

    active_threats: int = 0
    new_indicators: int = 0
    emerging_campaigns: int = 0
    loss_trend: list[dict[str, Any]] = Field(default_factory=list)
    source_breakdown: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Entity endpoints (S2-01)
# ---------------------------------------------------------------------------


@router.get("/entities", response_model=EntityListResponse)
def list_entities(
    entity_type: str | None = Query(None, description="Filter by entity type"),
    status: str | None = Query(None, description="Filter by status (active/dormant/flagged)"),
    min_case_count: int | None = Query(None, ge=0, description="Minimum case count"),
    min_loss: float | None = Query(None, ge=0, description="Minimum cumulative loss"),
    order_by: str = Query("case_count", description="Sort column"),
    descending: bool = Query(True, description="Sort direction"),
    limit: int = Query(50, ge=1, le=500, description="Page size"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    store: AnalyticsStore = Depends(get_analytics_store),
    user: dict[str, str] = Depends(require_token),
) -> EntityListResponse:
    """List entities with optional filters, pagination, and sorting.

    Returns pre-computed entity stats from the aggregation pipeline.

    Args:
        entity_type: Filter by entity type.
        status: Filter by entity status.
        min_case_count: Minimum case count threshold.
        min_loss: Minimum loss sum threshold.
        order_by: Column to sort by.
        descending: Sort direction.
        limit: Max rows to return.
        offset: Pagination offset.
        store: Injected AnalyticsStore.

    Returns:
        Paginated entity stats list.
    """
    items = store.list_entity_stats(
        entity_type=entity_type,
        status=status,
        min_case_count=min_case_count,
        min_loss=min_loss,
        order_by=order_by,
        descending=descending,
        limit=limit,
        offset=offset,
    )
    if _is_researcher(user):
        items = [_anonymize_entity(i) for i in items]
    return EntityListResponse(
        items=[EntityStatResponse.model_validate(i) for i in items],
        count=len(items),
        limit=limit,
        offset=offset,
    )


@router.get("/entities/{entity_type}/{canonical_value}", response_model=EntityDetailResponse)
def get_entity(
    entity_type: str,
    canonical_value: str,
    store: AnalyticsStore = Depends(get_analytics_store),
    campaign_store: ThreatCampaignStore = Depends(get_campaign_store),
    user: dict[str, str] = Depends(require_token),
) -> EntityDetailResponse:
    """Fetch detail for a specific entity with real-time drill-down.

    Combines pre-computed stats with campaign linkage information.
    Researcher role gets anonymized view.

    Args:
        entity_type: The entity type (e.g., bank_account, crypto_wallet).
        canonical_value: The normalized entity value.
        store: Injected AnalyticsStore.
        campaign_store: Injected ThreatCampaignStore.
        user: Authenticated user context.

    Returns:
        Entity detail dict.

    Raises:
        HTTPException: If the entity is not found or researcher lacks access.
    """
    if _is_researcher(user):
        raise HTTPException(
            status_code=403,
            detail="Researcher role cannot access individual entity details",
        )
    stat = store.get_entity_stat(entity_type, canonical_value)
    if not stat:
        raise HTTPException(status_code=404, detail="Entity not found")

    # Enrich with campaign names if campaign_ids present
    campaign_ids = stat.get("campaign_ids") or []
    campaigns = []
    for cid in campaign_ids:
        campaign = campaign_store.get_campaign(cid)
        if campaign:
            campaigns.append({"id": cid, "name": campaign.get("name", "")})

    return EntityDetailResponse.model_validate({**stat, "campaigns": campaigns})


# ---------------------------------------------------------------------------
# Entity sparkline endpoint (S2-04)
# ---------------------------------------------------------------------------


@router.get("/entities/{entity_type}/{canonical_value}/activity", response_model=list[ActivityPoint])
def get_entity_activity(
    entity_type: str,
    canonical_value: str,
    store: AnalyticsStore = Depends(get_analytics_store),
) -> list[ActivityPoint]:
    """Return weekly case counts over the entity's lifetime for sparkline rendering.

    Args:
        entity_type: The entity type.
        canonical_value: The normalized entity value.
        store: Injected AnalyticsStore.

    Returns:
        List of weekly activity data points.

    Raises:
        HTTPException: If the entity is not found.
    """
    stat = store.get_entity_stat(entity_type, canonical_value)
    if not stat:
        raise HTTPException(status_code=404, detail="Entity not found")

    activity = store.get_entity_activity(entity_type, canonical_value)
    return [ActivityPoint.model_validate(a) for a in activity]


# ---------------------------------------------------------------------------
# Entity mini-graph endpoint (S2-05)
# ---------------------------------------------------------------------------


@router.get(
    "/entities/{entity_type}/{canonical_value}/neighbors",
    response_model=NeighborGraphResponse,
)
def get_entity_neighbors(
    entity_type: str,
    canonical_value: str,
    store: AnalyticsStore = Depends(get_analytics_store),
) -> NeighborGraphResponse:
    """Return the 1-hop co-occurrence graph for an entity.

    Entities that appear in the same cases as the seed entity are returned
    as neighbors. Edge weight is the number of shared cases.

    Args:
        entity_type: The entity type.
        canonical_value: The normalized entity value.
        store: Injected AnalyticsStore.

    Returns:
        Neighbor graph with nodes and edges.

    Raises:
        HTTPException: If the entity is not found.
    """
    stat = store.get_entity_stat(entity_type, canonical_value)
    if not stat:
        raise HTTPException(status_code=404, detail="Entity not found")

    neighbors_data = store.get_entity_neighbors(entity_type, canonical_value)

    seed_id = f"{entity_type}:{canonical_value}"
    nodes = [
        NeighborNode(
            id=seed_id,
            label=canonical_value,
            entity_type=entity_type,
            case_count=stat.get("case_count", 0),
        )
    ]
    edges = []

    for neighbor in neighbors_data:
        n_id = f"{neighbor['entity_type']}:{neighbor['canonical_value']}"
        nodes.append(
            NeighborNode(
                id=n_id,
                label=neighbor["canonical_value"],
                entity_type=neighbor["entity_type"],
                case_count=neighbor.get("case_count", 0),
            )
        )
        edges.append(
            NeighborEdge(
                source=seed_id,
                target=n_id,
                weight=neighbor.get("shared_cases", 1),
            )
        )

    return NeighborGraphResponse(seed=seed_id, nodes=nodes, edges=edges)


# ---------------------------------------------------------------------------
# Indicator endpoints (S2-02)
# ---------------------------------------------------------------------------


@router.get("/indicators", response_model=IndicatorListResponse)
def list_indicators(
    category: str | None = Query(None, description="Segment: bank/crypto/payments/ip/domain"),
    min_case_count: int | None = Query(None, ge=0, description="Minimum case count"),
    order_by: str = Query("case_count", description="Sort column"),
    descending: bool = Query(True, description="Sort direction"),
    limit: int = Query(50, ge=1, le=500, description="Page size"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    store: AnalyticsStore = Depends(get_analytics_store),
    user: dict[str, str] = Depends(require_token),
) -> IndicatorListResponse:
    """List indicators with optional category filter and pagination.

    Supports segmentation tabs: all, bank, crypto, payments, ip, domain.

    Args:
        category: Indicator category filter.
        min_case_count: Minimum case count threshold.
        order_by: Sort column.
        descending: Sort direction.
        limit: Page size.
        offset: Pagination offset.
        store: Injected AnalyticsStore.
        user: Authenticated user context.

    Returns:
        Paginated indicator stats list.
    """
    items = store.list_indicator_stats(
        category=category,
        min_case_count=min_case_count,
        order_by=order_by,
        descending=descending,
        limit=limit,
        offset=offset,
    )
    if _is_researcher(user):
        items = [_anonymize_indicator(i) for i in items]
    prepared = [_map_indicator_fields(i) for i in items]
    return IndicatorListResponse(
        items=[IndicatorStatResponse.model_validate(p) for p in prepared],
        count=len(items),
        limit=limit,
        offset=offset,
    )


@router.get("/indicators/{indicator_id}", response_model=IndicatorStatResponse)
def get_indicator(
    indicator_id: str,
    store: AnalyticsStore = Depends(get_analytics_store),
    user: dict[str, str] = Depends(require_token),
) -> IndicatorStatResponse:
    """Fetch detail for a specific indicator.

    Args:
        indicator_id: The indicator UUID.
        store: Injected AnalyticsStore.
        user: Authenticated user context.

    Returns:
        Indicator stats dict.

    Raises:
        HTTPException: If the indicator is not found or researcher lacks access.
    """
    if _is_researcher(user):
        raise HTTPException(
            status_code=403,
            detail="Researcher role cannot access individual indicator details",
        )
    stat = store.get_indicator_stat(indicator_id)
    if not stat:
        raise HTTPException(status_code=404, detail="Indicator not found")
    return IndicatorStatResponse.model_validate(_map_indicator_fields(stat))


# ---------------------------------------------------------------------------
# Dashboard widgets endpoint (S2-03)
# ---------------------------------------------------------------------------


@router.get("/dashboard", response_model=DashboardWidgetsResponse)
def get_dashboard_widgets(
    store: AnalyticsStore = Depends(get_analytics_store),
    campaign_store: ThreatCampaignStore = Depends(get_campaign_store),
) -> DashboardWidgetsResponse:
    """Return aggregated widget data for the Intelligence Dashboard.

    Combines entity stats, indicator stats, campaign stats, and platform KPIs
    to build the widgetboard summary.

    Args:
        store: Injected AnalyticsStore.
        campaign_store: Injected ThreatCampaignStore.

    Returns:
        Dashboard widget data.
    """
    # Active threats = entities with status 'active' or 'flagged'
    all_active = store.list_entity_stats(status="active", limit=10000)
    all_flagged = store.list_entity_stats(status="flagged", limit=10000)
    active_threats = len(all_active) + len(all_flagged)

    # New indicators = count from latest daily KPI
    latest_kpi = store.get_latest_kpi(period_type="daily")
    new_indicators = latest_kpi.get("new_indicators", 0) if latest_kpi else 0

    # Emerging campaigns
    emerging = campaign_store.list_campaigns(status="emerging")
    emerging_campaigns = len(emerging)

    # Loss trend = last 12 weekly KPIs
    weekly_kpis = store.list_platform_kpis(period_type="weekly", limit=12)
    loss_trend = [
        {"period": str(kpi.get("period_start", "")), "loss": float(kpi.get("total_loss", 0))} for kpi in weekly_kpis
    ]

    # Source breakdown from latest KPI
    source_breakdown = []
    if latest_kpi:
        source_breakdown = [
            {"source": "proactive", "count": latest_kpi.get("proactive_cases", 0)},
            {"source": "reactive", "count": latest_kpi.get("reactive_cases", 0)},
        ]

    return DashboardWidgetsResponse(
        active_threats=active_threats,
        new_indicators=new_indicators,
        emerging_campaigns=emerging_campaigns,
        loss_trend=loss_trend,
        source_breakdown=source_breakdown,
    )


# ---------------------------------------------------------------------------
# Global Search enhancement (S2-06) — entity/indicator type facets
# ---------------------------------------------------------------------------


@router.get("/search/facets")
def get_search_facets(
    store: AnalyticsStore = Depends(get_analytics_store),
) -> dict[str, Any]:
    """Return entity and indicator type facets for Global Search enhancement.

    Provides counts per entity type and indicator category to power
    search overlay filters.

    Args:
        store: Injected AnalyticsStore.

    Returns:
        Dict with entity_types and indicator_categories facets.
    """
    # Entity type facets
    all_entities = store.list_entity_stats(limit=10000)
    entity_type_counts: dict[str, int] = {}
    for e in all_entities:
        et = e.get("entity_type", "unknown")
        entity_type_counts[et] = entity_type_counts.get(et, 0) + 1

    # Indicator category facets
    all_indicators = store.list_indicator_stats(limit=10000)
    indicator_category_counts: dict[str, int] = {}
    for ind in all_indicators:
        cat = ind.get("category", "unknown")
        indicator_category_counts[cat] = indicator_category_counts.get(cat, 0) + 1

    return {
        "entity_types": [{"type": k, "count": v} for k, v in sorted(entity_type_counts.items())],
        "indicator_categories": [{"category": k, "count": v} for k, v in sorted(indicator_category_counts.items())],
    }
