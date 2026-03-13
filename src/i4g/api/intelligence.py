"""Intelligence API router — Entity Explorer, Indicator Registry, Dashboard widgets.

Provides endpoints for browsing pre-computed entity and indicator stats,
fetching dashboard widget data, entity sparklines, and entity neighbor graphs.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field, field_validator

from i4g.api.auth import require_token
from i4g.api.camel import CamelModel
from i4g.api.roles import Role, has_role
from i4g.services.factories import build_analytics_store, build_threat_campaign_store
from i4g.services.lea_referral import LeaReferralEngine
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

    @field_validator("campaign_ids", mode="before")
    @classmethod
    def _parse_campaign_ids(cls, v: Any) -> list[str] | None:
        if isinstance(v, str):
            return json.loads(v)
        return v

    @field_validator("first_seen_at", "last_seen_at", "updated_at", mode="before")
    @classmethod
    def _coerce_datetimes(cls, v: Any) -> str | None:
        if isinstance(v, datetime):
            return v.isoformat()
        return v


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

    @field_validator("first_seen_at", "last_seen_at", "updated_at", mode="before")
    @classmethod
    def _coerce_datetimes(cls, v: Any) -> str | None:
        if isinstance(v, datetime):
            return v.isoformat()
        return v


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


@router.get("/entities/types", response_model=list[str])
def list_entity_types(
    store: AnalyticsStore = Depends(get_analytics_store),
    _user: dict[str, str] = Depends(require_token),
) -> list[str]:
    """Return distinct entity types present in entity_stats."""
    return store.list_entity_types()


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


# ---------------------------------------------------------------------------
# Campaign Intelligence endpoints (S3-04)
# ---------------------------------------------------------------------------


class ThreatCampaignResponse(CamelModel):
    """Threat campaign list item."""

    campaign_id: str
    name: str
    description: str | None = None
    origin: str = "manual"
    status: str = "emerging"
    risk_score: float = 0.0
    taxonomy_rollup: Any | None = None
    metadata: Any | None = None
    created_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    case_count: int = 0
    loss_sum: float = 0.0
    indicator_count: int = 0


class ThreatCampaignListResponse(CamelModel):
    """Paginated threat campaign list."""

    items: list[ThreatCampaignResponse]
    count: int
    limit: int
    offset: int


class ThreatCampaignDetailResponse(ThreatCampaignResponse):
    """Campaign detail with linked entities, timeline, and eCX status."""

    cases: list[dict[str, Any]] = Field(default_factory=list)
    entity_types: dict[str, int] = Field(default_factory=dict)
    ssi_links: list[dict[str, Any]] = Field(default_factory=list)
    ecx_status: str | None = None


class CampaignTimelinePoint(CamelModel):
    """A single point on the campaign timeline."""

    date: str
    case_count: int = 0


class CampaignManagementRequest(CamelModel):
    """Request body for campaign management operations."""

    action: str
    name: str | None = None
    description: str | None = None
    status: str | None = None
    case_ids: list[str] | None = None
    annotation: str | None = None
    merge_source_ids: list[str] | None = None
    split_groups: dict[str, list[str]] | None = None


@router.get("/campaigns", response_model=ThreatCampaignListResponse)
def list_threat_campaigns(
    status: str | None = Query(None, description="Filter by lifecycle status"),
    order_by: str = Query("updated_at", description="Sort column"),
    descending: bool = Query(True, description="Sort direction"),
    limit: int = Query(50, ge=1, le=500, description="Page size"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    campaign_store: ThreatCampaignStore = Depends(get_campaign_store),
    analytics_store: AnalyticsStore = Depends(get_analytics_store),
) -> ThreatCampaignListResponse:
    """List threat campaigns with stats enrichment.

    Combines campaign metadata from ``threat_campaigns`` with pre-computed
    stats from ``campaign_stats``.

    Args:
        status: Lifecycle status filter.
        order_by: Sort column name.
        descending: Sort descending when True.
        limit: Page size.
        offset: Pagination offset.
        campaign_store: Injected ThreatCampaignStore.
        analytics_store: Injected AnalyticsStore.

    Returns:
        Paginated list of campaigns with stats.
    """
    campaigns = campaign_store.list_campaigns(status=status, limit=limit, offset=offset)
    items = []
    for c in campaigns:
        cid = c.get("campaign_id", "")
        stat = analytics_store.get_campaign_stat(cid) or {}
        items.append(
            ThreatCampaignResponse(
                campaign_id=cid,
                name=c.get("name", ""),
                description=c.get("description"),
                origin=c.get("origin", "manual"),
                status=c.get("status", "emerging"),
                risk_score=float(c.get("risk_score") or stat.get("risk_score", 0)),
                taxonomy_rollup=c.get("taxonomy_rollup"),
                metadata=c.get("metadata"),
                created_by=c.get("created_by"),
                created_at=str(c["created_at"]) if c.get("created_at") else None,
                updated_at=str(c["updated_at"]) if c.get("updated_at") else None,
                case_count=int(stat.get("case_count", 0)),
                loss_sum=float(stat.get("loss_sum", 0)),
                indicator_count=int(stat.get("indicator_count", 0)),
            )
        )
    return ThreatCampaignListResponse(items=items, count=len(items), limit=limit, offset=offset)


@router.get("/campaigns/{campaign_id}", response_model=ThreatCampaignDetailResponse)
def get_threat_campaign_detail(
    campaign_id: str,
    campaign_store: ThreatCampaignStore = Depends(get_campaign_store),
    analytics_store: AnalyticsStore = Depends(get_analytics_store),
) -> ThreatCampaignDetailResponse:
    """Get detailed threat campaign view with metrics, cases, and entity breakdown.

    Args:
        campaign_id: The campaign UUID.
        campaign_store: Injected ThreatCampaignStore.
        analytics_store: Injected AnalyticsStore.

    Returns:
        Campaign detail including linked cases and entity type counts.

    Raises:
        HTTPException: If the campaign is not found.
    """
    campaign = campaign_store.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    stat = analytics_store.get_campaign_stat(campaign_id) or {}
    linked_cases = campaign_store.get_campaign_cases(campaign_id)
    entity_types = stat.get("entity_count_by_type") or {}
    if isinstance(entity_types, str):
        import json

        entity_types = json.loads(entity_types)

    return ThreatCampaignDetailResponse(
        campaign_id=campaign_id,
        name=campaign.get("name", ""),
        description=campaign.get("description"),
        origin=campaign.get("origin", "manual"),
        status=campaign.get("status", "emerging"),
        risk_score=float(campaign.get("risk_score") or stat.get("risk_score", 0)),
        taxonomy_rollup=campaign.get("taxonomy_rollup"),
        metadata=campaign.get("metadata"),
        created_by=campaign.get("created_by"),
        created_at=str(campaign["created_at"]) if campaign.get("created_at") else None,
        updated_at=str(campaign["updated_at"]) if campaign.get("updated_at") else None,
        case_count=int(stat.get("case_count", 0)),
        loss_sum=float(stat.get("loss_sum", 0)),
        indicator_count=int(stat.get("indicator_count", 0)),
        cases=linked_cases,
        entity_types=entity_types if isinstance(entity_types, dict) else {},
    )


# ---------------------------------------------------------------------------
# S3-05  Campaign management: rename, merge, split, link/unlink, status, annotate
# ---------------------------------------------------------------------------


@router.post("/campaigns/{campaign_id}/manage")
def manage_campaign(
    campaign_id: str,
    payload: CampaignManagementRequest,
    campaign_store: ThreatCampaignStore = Depends(get_campaign_store),
    user: dict[str, str] = Depends(require_token),
) -> dict[str, Any]:
    """Execute a management action on a threat campaign.

    Supported actions: rename, update_status, link_cases, unlink_cases,
    merge, split, annotate.

    Args:
        campaign_id: The campaign UUID.
        payload: Management action request.
        campaign_store: Injected ThreatCampaignStore.
        user: Authenticated user context.

    Returns:
        Dict with action result.

    Raises:
        HTTPException: 404 if campaign not found, 400 for invalid action.
    """
    campaign = campaign_store.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    username = user.get("username", "unknown")
    action = payload.action

    if action == "rename":
        if not payload.name:
            raise HTTPException(status_code=400, detail="Name required for rename")
        campaign_store.update_campaign(campaign_id, name=payload.name, description=payload.description)
        logger.info("Campaign %s renamed to %r by %s", campaign_id, payload.name, username)
        return {"action": "rename", "campaign_id": campaign_id, "success": True}

    if action == "update_status":
        if not payload.status:
            raise HTTPException(status_code=400, detail="Status required")
        campaign_store.update_status(campaign_id, status=payload.status)
        logger.info("Campaign %s status → %s by %s", campaign_id, payload.status, username)
        return {"action": "update_status", "campaign_id": campaign_id, "success": True}

    if action == "link_cases":
        for case_id in payload.case_ids or []:
            campaign_store.link_case(campaign_id, case_id, linked_by=f"manual:{username}")
        return {"action": "link_cases", "campaign_id": campaign_id, "linked": len(payload.case_ids or [])}

    if action == "unlink_cases":
        for case_id in payload.case_ids or []:
            campaign_store.unlink_case(campaign_id, case_id)
        return {"action": "unlink_cases", "campaign_id": campaign_id, "unlinked": len(payload.case_ids or [])}

    if action == "merge":
        source_ids = payload.merge_source_ids or []
        if not source_ids:
            raise HTTPException(status_code=400, detail="merge_source_ids required")
        new_id = campaign_store.merge_campaigns(
            [campaign_id, *source_ids],
            target_name=payload.name or campaign.get("name", "Merged Campaign"),
            merged_by=username,
        )
        logger.info("Campaigns merged into %s by %s", new_id, username)
        return {"action": "merge", "new_campaign_id": new_id, "success": True}

    if action == "split":
        groups = payload.split_groups or {}
        if not groups:
            raise HTTPException(status_code=400, detail="split_groups required")
        result = campaign_store.split_campaign(campaign_id, case_groups=groups, split_by=username)
        logger.info("Campaign %s split into %d groups by %s", campaign_id, len(result), username)
        return {"action": "split", "new_campaigns": result, "success": True}

    if action == "annotate":
        # Store annotation in campaign metadata
        meta = campaign.get("metadata") or {}
        if isinstance(meta, str):
            import json

            meta = json.loads(meta)
        annotations = meta.get("annotations", [])
        annotations.append({"text": payload.annotation, "by": username})
        meta["annotations"] = annotations
        campaign_store.update_campaign(campaign_id, metadata=meta)
        return {"action": "annotate", "campaign_id": campaign_id, "success": True}

    raise HTTPException(status_code=400, detail=f"Unknown action: {action}")


# ---------------------------------------------------------------------------
# S3-06  Campaign timeline
# ---------------------------------------------------------------------------


@router.get("/campaigns/{campaign_id}/timeline", response_model=list[CampaignTimelinePoint])
def get_campaign_timeline(
    campaign_id: str,
    campaign_store: ThreatCampaignStore = Depends(get_campaign_store),
) -> list[CampaignTimelinePoint]:
    """Return cases per day over the campaign lifetime for timeline chart.

    Args:
        campaign_id: The campaign UUID.
        campaign_store: Injected ThreatCampaignStore.

    Returns:
        List of daily case count data points.

    Raises:
        HTTPException: If the campaign is not found.
    """
    campaign = campaign_store.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    linked = campaign_store.get_campaign_cases(campaign_id)

    # Aggregate by date
    date_counts: dict[str, int] = {}
    for link in linked:
        linked_at = link.get("linked_at", "")
        if linked_at:
            day = str(linked_at)[:10]
            date_counts[day] = date_counts.get(day, 0) + 1

    return [CampaignTimelinePoint(date=d, case_count=c) for d, c in sorted(date_counts.items())]


# ---------------------------------------------------------------------------
# S3-07  Campaign network graph
# ---------------------------------------------------------------------------


@router.get("/campaigns/{campaign_id}/graph")
def get_campaign_graph(
    campaign_id: str,
    campaign_store: ThreatCampaignStore = Depends(get_campaign_store),
    analytics_store: AnalyticsStore = Depends(get_analytics_store),
) -> dict[str, Any]:
    """Return a scoped entity co-occurrence graph for a campaign.

    Builds a graph of entities that appear across the campaign's linked
    cases, with edges representing co-occurrence within the same case.

    Args:
        campaign_id: The campaign UUID.
        campaign_store: Injected ThreatCampaignStore.
        analytics_store: Injected AnalyticsStore.

    Returns:
        Graph payload with nodes and edges.

    Raises:
        HTTPException: If the campaign is not found.
    """
    campaign = campaign_store.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    linked = campaign_store.get_campaign_cases(campaign_id)
    case_ids = [link["case_id"] for link in linked]

    if not case_ids:
        return {"nodes": [], "edges": [], "node_count": 0, "edge_count": 0}

    # Collect entity stats for entities involved in campaign cases
    all_entities = analytics_store.list_entity_stats(limit=10000)
    campaign_entities = [e for e in all_entities if any(cid in str(e.get("campaign_ids", "")) for cid in case_ids)]

    # Build nodes
    nodes = []
    for ent in campaign_entities[:200]:  # Cap at 200 nodes for performance
        node_id = f"{ent.get('entity_type', '')}:{ent.get('canonical_value', '')}"
        nodes.append(
            {
                "id": node_id,
                "label": ent.get("canonical_value", ""),
                "entityType": ent.get("entity_type", ""),
                "caseCount": ent.get("case_count", 0),
                "riskScore": float(ent.get("max_risk_score", 0)),
            }
        )

    # Build co-occurrence edges (simplified — entities that share campaign)
    edges = []
    for i, n1 in enumerate(nodes):
        for n2 in nodes[i + 1 :]:
            if n1["entityType"] != n2["entityType"]:
                edges.append(
                    {
                        "source": n1["id"],
                        "target": n2["id"],
                        "weight": 1,
                        "edgeType": "same-campaign",
                    }
                )

    return {
        "nodes": nodes,
        "edges": edges[:500],  # Cap edges
        "node_count": len(nodes),
        "edge_count": len(edges),
    }


# ---------------------------------------------------------------------------
# S3-11  LEA referral suggestions
# ---------------------------------------------------------------------------


class LeaSuggestionItem(CamelModel):
    """A single LEA referral suggestion."""

    suggestion_id: str
    target_type: str
    target_id: str
    target_label: str
    reasons: list[str]
    loss_sum: float = 0.0
    case_count: int = 0
    risk_score: float = 0.0
    ecx_corroborated: bool = False


class LeaSuggestionResponse(CamelModel):
    """Wrapped response for LEA referral suggestions."""

    suggestions: list[LeaSuggestionItem]
    count: int


@router.get("/lea-suggestions", response_model=LeaSuggestionResponse)
def get_lea_suggestions(
    limit: int = Query(20, ge=1, le=100, description="Max suggestions"),
    analytics_store: AnalyticsStore = Depends(get_analytics_store),
    campaign_store: ThreatCampaignStore = Depends(get_campaign_store),
) -> LeaSuggestionResponse:
    """List entities and campaigns meeting LEA referral thresholds.

    Evaluates all entities and campaigns against configurable criteria:
    cumulative loss >$50K, >5 linked cases, or eCrimeX corroboration.

    Args:
        limit: Maximum number of suggestions.
        analytics_store: Injected AnalyticsStore.
        campaign_store: Injected ThreatCampaignStore.

    Returns:
        Wrapped LEA referral suggestions sorted by loss descending.
    """
    engine = LeaReferralEngine(analytics_store, campaign_store)
    suggestions = engine.get_suggestions(limit=limit)
    items = [LeaSuggestionItem(**s.to_dict()) for s in suggestions]
    return LeaSuggestionResponse(suggestions=items, count=len(items))
