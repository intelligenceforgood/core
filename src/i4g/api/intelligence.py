"""Intelligence API router — Entity Explorer, Indicator Registry, Dashboard widgets.

Provides endpoints for browsing pre-computed entity and indicator stats,
fetching dashboard widget data, entity sparklines, and entity neighbor graphs.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field, field_validator

from i4g.api.auth import require_token
from i4g.api.camel import CamelModel
from i4g.api.roles import Role, is_researcher
from i4g.services.factories import (
    build_analytics_store,
    build_annotation_store,
    build_threat_campaign_store,
    build_watchlist_store,
)
from i4g.services.lea_referral import LeaReferralEngine
from i4g.store import sql as sql_schema
from i4g.store.analytics_store import AnalyticsStore
from i4g.store.annotation_store import AnnotationStore
from i4g.store.threat_campaign_store import ThreatCampaignStore
from i4g.store.watchlist_store import WatchlistStore
from i4g.utils.entity_types import THREAT_ENTITY_TYPES, entity_type_label, normalize_entity_type

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


def get_annotation_store() -> AnnotationStore:
    """Return an AnnotationStore instance."""
    return build_annotation_store()


def get_watchlist_store() -> WatchlistStore:
    """Return a WatchlistStore instance."""
    return build_watchlist_store()


def _is_researcher(user: dict[str, str]) -> bool:
    """Return True if the user has only researcher-level access."""
    return is_researcher(user)


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


def _compute_lea_referral_summary(linked_cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute LEA referral summary from linked case rows.

    Args:
        linked_cases: List of case dicts (from campaign case linkage).

    Returns:
        Dict with referred_count, total, and agencies list.
    """
    total = len(linked_cases)
    referred = 0
    agencies: set[str] = set()
    for case in linked_cases:
        if case.get("lea_referred_at") or case.get("lea_agency"):
            referred += 1
            agency = case.get("lea_agency")
            if agency:
                agencies.add(agency)
    return {"referred_count": referred, "total": total, "agencies": sorted(agencies)}


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
    """Entity stats with campaign linkage and optional blockchain enrichment."""

    campaigns: list[dict[str, str]] = Field(default_factory=list)
    blockchain_enrichment: dict[str, Any] | None = Field(
        default=None,
        description="Blockchain analytics data for wallet entities (vendor risk label, cluster, exchange).",
    )


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


class EntityTypeLabelItem(CamelModel):
    """An entity type with its user-friendly label."""

    value: str
    label: str


@router.get("/entities/type-labels", response_model=list[EntityTypeLabelItem])
def list_entity_type_labels(
    store: AnalyticsStore = Depends(get_analytics_store),
    _user: dict[str, str] = Depends(require_token),
) -> list[EntityTypeLabelItem]:
    """Return entity types with user-friendly display labels."""
    types = store.list_entity_types()
    return [EntityTypeLabelItem(value=t, label=entity_type_label(t)) for t in types]


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
    total = store.count_entity_stats(
        entity_type=entity_type,
        status=status,
        min_case_count=min_case_count,
        min_loss=min_loss,
    )
    if _is_researcher(user):
        items = [_anonymize_entity(i) for i in items]
    return EntityListResponse(
        items=[EntityStatResponse.model_validate(i) for i in items],
        count=total,
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

    # Blockchain enrichment for wallet entities (S6-04)
    blockchain_data = None
    if entity_type in ("crypto_wallet", "wallet_address"):
        from i4g.services.enrichment.blockchain import enrich_wallet

        try:
            enrichment = enrich_wallet(canonical_value)
            blockchain_data = enrichment.to_dict()
        except Exception:
            logger.warning("Blockchain enrichment failed for %s", canonical_value, exc_info=True)

    return EntityDetailResponse.model_validate(
        {**stat, "campaigns": campaigns, "blockchain_enrichment": blockchain_data}
    )


# ---------------------------------------------------------------------------
# Entity sparkline endpoint (S2-04)
# ---------------------------------------------------------------------------


@router.get("/entities/{entity_type}/{canonical_value}/activity", response_model=list[ActivityPoint])
def get_entity_activity(
    entity_type: str,
    canonical_value: str,
    store: AnalyticsStore = Depends(get_analytics_store),
    user: dict[str, str] = Depends(require_token),
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
    if _is_researcher(user):
        raise HTTPException(status_code=403, detail="Researcher role cannot access entity activity data")
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
    user: dict[str, str] = Depends(require_token),
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
    if _is_researcher(user):
        raise HTTPException(status_code=403, detail="Researcher role cannot access entity neighbor data")
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
# Entity → Cases endpoint
# ---------------------------------------------------------------------------


class EntityCaseSummary(CamelModel):
    """A case summary for entity→cases lookup."""

    case_id: str
    title: str | None = None
    status: str | None = None
    classification: str | None = None
    risk_score: float | None = None
    created_at: str | None = None

    @field_validator("created_at", mode="before")
    @classmethod
    def _coerce_datetime(cls, v: Any) -> str | None:
        if isinstance(v, datetime):
            return v.isoformat()
        return v


class EntityCasesResponse(CamelModel):
    """Paginated list of cases containing a specific entity."""

    entity_type: str
    canonical_value: str
    items: list[EntityCaseSummary]
    count: int
    limit: int
    offset: int


@router.get(
    "/entities/{entity_type}/{canonical_value}/cases",
    response_model=EntityCasesResponse,
)
def get_entity_cases(
    entity_type: str,
    canonical_value: str,
    limit: int = Query(20, ge=1, le=100, description="Page size"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    store: AnalyticsStore = Depends(get_analytics_store),
    user: dict[str, str] = Depends(require_token),
) -> EntityCasesResponse:
    """Return a paginated list of cases containing a specific entity.

    Joins the entities table with cases to provide case summaries for
    each case where this entity appears.

    Args:
        entity_type: The entity type.
        canonical_value: The normalized entity value.
        limit: Max rows per page.
        offset: Pagination offset.
        store: Injected AnalyticsStore (used to verify entity exists).
        user: Authenticated user context.

    Returns:
        Paginated case summaries for the entity.

    Raises:
        HTTPException: If the entity is not found or researcher lacks access.
    """
    if _is_researcher(user):
        raise HTTPException(status_code=403, detail="Researcher role cannot access entity case data")
    stat = store.get_entity_stat(entity_type, canonical_value)
    if not stat:
        raise HTTPException(status_code=404, detail="Entity not found")

    entities_t = sql_schema.entities
    cases_t = sql_schema.cases
    sf = sql_schema.session_factory()
    with sf() as session:
        # Count total cases
        count_q = (
            sa.select(sa.func.count(sa.distinct(entities_t.c.case_id)))
            .where(entities_t.c.entity_type == entity_type)
            .where(entities_t.c.canonical_value == canonical_value)
        )
        total = session.execute(count_q).scalar() or 0

        # Fetch paginated case summaries
        case_q = (
            sa.select(
                cases_t.c.case_id,
                cases_t.c.title,
                cases_t.c.status,
                cases_t.c.classification,
                cases_t.c.risk_score,
                cases_t.c.created_at,
            )
            .join(entities_t, entities_t.c.case_id == cases_t.c.case_id)
            .where(entities_t.c.entity_type == entity_type)
            .where(entities_t.c.canonical_value == canonical_value)
            .distinct()
            .order_by(cases_t.c.created_at.desc().nullslast())
            .limit(limit)
            .offset(offset)
        )
        rows = session.execute(case_q).all()

    items = [
        EntityCaseSummary(
            case_id=r[0],
            title=r[1],
            status=r[2],
            classification=r[3],
            risk_score=float(r[4]) if r[4] is not None else None,
            created_at=r[5],
        )
        for r in rows
    ]

    return EntityCasesResponse(
        entity_type=entity_type,
        canonical_value=canonical_value,
        items=items,
        count=total,
        limit=limit,
        offset=offset,
    )


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
    total = store.count_indicator_stats(
        category=category,
        min_case_count=min_case_count,
    )
    if _is_researcher(user):
        items = [_anonymize_indicator(i) for i in items]
    prepared = [_map_indicator_fields(i) for i in items]
    return IndicatorListResponse(
        items=[IndicatorStatResponse.model_validate(p) for p in prepared],
        count=total,
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
    # Active threats = threat-indicator entities (financial, contact, digital
    # infra) with status 'active' or 'flagged'.  Excludes contextual NER
    # types (person, organization, location) to avoid inflated counts after
    # LLM entity extraction.
    active_threats = store.count_entity_stats(
        status="active", entity_types=THREAT_ENTITY_TYPES
    ) + store.count_entity_stats(status="flagged", entity_types=THREAT_ENTITY_TYPES)

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

    id: str
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
    victim_count: int = 0

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _coerce_datetimes(cls, v: Any) -> str | None:
        if isinstance(v, datetime):
            return v.isoformat()
        return v


class ThreatCampaignListResponse(CamelModel):
    """Paginated threat campaign list."""

    items: list[ThreatCampaignResponse]
    count: int
    limit: int
    offset: int


class ThreatCampaignDetailResponse(ThreatCampaignResponse):
    """Campaign detail with linked entities, timeline, eCX status, and LEA referrals."""

    cases: list[dict[str, Any]] = Field(default_factory=list)
    entity_types: dict[str, int] = Field(default_factory=dict)
    ssi_links: list[dict[str, Any]] = Field(default_factory=list)
    ecx_status: str | None = None
    lea_referral_summary: dict[str, Any] = Field(
        default_factory=dict,
        description="Summary of LEA referral status across member cases (referred_count, total, agencies).",
    )


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
                id=cid,
                name=c.get("name", ""),
                description=c.get("description"),
                origin=c.get("origin", "manual"),
                status=c.get("status", "emerging"),
                risk_score=float(c.get("risk_score") or stat.get("risk_score", 0)),
                taxonomy_rollup=c.get("taxonomy_rollup"),
                metadata=c.get("metadata"),
                created_by=c.get("created_by"),
                created_at=c.get("created_at"),
                updated_at=c.get("updated_at"),
                case_count=int(stat.get("case_count", 0)),
                loss_sum=float(stat.get("loss_sum", 0)),
                indicator_count=int(stat.get("indicator_count", 0)),
                victim_count=int(stat.get("victim_count", 0)),
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
        entity_types = json.loads(entity_types)

    # Compute LEA referral summary across member cases (S6-08)
    lea_summary = _compute_lea_referral_summary(linked_cases)

    return ThreatCampaignDetailResponse(
        id=campaign_id,
        name=campaign.get("name", ""),
        description=campaign.get("description"),
        origin=campaign.get("origin", "manual"),
        status=campaign.get("status", "emerging"),
        risk_score=float(campaign.get("risk_score") or stat.get("risk_score", 0)),
        taxonomy_rollup=campaign.get("taxonomy_rollup"),
        metadata=campaign.get("metadata"),
        created_by=campaign.get("created_by"),
        created_at=campaign.get("created_at"),
        updated_at=campaign.get("updated_at"),
        case_count=int(stat.get("case_count", 0)),
        loss_sum=float(stat.get("loss_sum", 0)),
        indicator_count=int(stat.get("indicator_count", 0)),
        victim_count=int(stat.get("victim_count", 0)),
        cases=linked_cases,
        entity_types=entity_types if isinstance(entity_types, dict) else {},
        lea_referral_summary=lea_summary,
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
            day = linked_at.strftime("%Y-%m-%d") if isinstance(linked_at, datetime) else str(linked_at)[:10]
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


# ---------------------------------------------------------------------------
# S4-05  /api/intelligence/graph — full graph with seed/hops/filters
# ---------------------------------------------------------------------------


class GraphFilterParams(CamelModel):
    """Query parameters for graph exploration."""

    seed_id: str | None = None
    seed_type: str | None = None  # entity_id | case_id | campaign_id
    hops: int = 1
    entity_types: list[str] | None = None
    edge_types: list[str] | None = None
    risk_threshold: float | None = None
    date_start: str | None = None
    date_end: str | None = None
    limit: int = 200


class GraphNodeResponse(CamelModel):
    """Graph node representation."""

    id: str
    label: str
    entity_type: str
    case_count: int = 0
    risk_score: float = 0.0
    campaign_ids: list[str] = Field(default_factory=list)
    data: dict[str, Any] | None = None


class GraphEdgeResponse(CamelModel):
    """Graph edge representation."""

    source: str
    target: str
    weight: int = 1
    edge_type: str = "co-occurrence"
    case_ids: list[str] = Field(default_factory=list)


class GraphPayloadResponse(CamelModel):
    """Full graph payload."""

    nodes: list[GraphNodeResponse] = Field(default_factory=list)
    edges: list[GraphEdgeResponse] = Field(default_factory=list)
    node_count: int = 0
    edge_count: int = 0
    layout: dict[str, dict[str, float]] | None = None


@router.get("/graph", response_model=GraphPayloadResponse)
def get_intelligence_graph(
    seed: str = Query(..., description="Seed node ID (entity_type:canonical_value, case_id, or campaign_id)"),
    seed_type: str = Query("entity", description="Seed type: entity, case, or campaign"),
    hops: int = Query(1, ge=1, le=3, description="Number of hops to expand"),
    entity_types: str | None = Query(None, description="Comma-separated entity type filter"),
    edge_types: str | None = Query(None, description="Comma-separated edge type filter"),
    risk_threshold: float | None = Query(None, ge=0.0, le=100.0, description="Minimum risk score"),
    limit: int = Query(200, ge=1, le=2000, description="Max nodes returned"),
    analytics_store: AnalyticsStore = Depends(get_analytics_store),
    campaign_store: ThreatCampaignStore = Depends(get_campaign_store),
) -> GraphPayloadResponse:
    """Return a graph payload seeded from an entity, case, or campaign.

    Constructs a co-occurrence graph using pre-computed entity stats and
    returns nodes, edges, and optional server-side layout positions for
    large graphs (>500 nodes).

    Args:
        seed: Seed node identifier.
        seed_type: Type of the seed (entity, case, campaign).
        hops: Number of BFS hops from the seed.
        entity_types: Comma-separated entity type filter.
        edge_types: Comma-separated edge type filter.
        risk_threshold: Minimum risk score filter.
        limit: Maximum number of nodes to return.
        analytics_store: Injected AnalyticsStore.
        campaign_store: Injected ThreatCampaignStore.

    Returns:
        Graph payload with nodes, edges, counts, and optional layout.
    """
    # Parse entity type filter
    type_filter = set(t.strip() for t in entity_types.split(",")) if entity_types else None

    # --- SQL-based iterative neighbor expansion ---
    # Instead of loading all entities into memory and building a global
    # NetworkX graph, we expand outward from the seed using the store's
    # get_entity_neighbors (SQL co-occurrence query).  This keeps memory
    # proportional to the result set, not the whole database.

    if seed_type == "campaign":
        # Campaign seed: not yet supported via SQL-based expansion.
        # Return empty graph — the campaign detail page has its own graph.
        return GraphPayloadResponse(nodes=[], edges=[], node_count=0, edge_count=0)

    if seed_type == "case":
        # Case seed: find all entities for the case, then build a graph
        # by expanding from each entity.
        entities_t = sql_schema.entities
        sf = sql_schema.session_factory()
        with sf() as session:
            case_entities = session.execute(
                sa.select(
                    sa.distinct(entities_t.c.entity_type),
                    entities_t.c.canonical_value,
                ).where(entities_t.c.case_id == seed)
            ).all()
            if not case_entities:
                return GraphPayloadResponse(nodes=[], edges=[], node_count=0, edge_count=0)

        node_map: dict[str, GraphNodeResponse] = {}
        edge_list: list[GraphEdgeResponse] = []
        seen_edges: set[tuple[str, str]] = set()

        # Add all case entities as seed nodes
        for ce_et, ce_cv in case_entities:
            ce_id = f"{ce_et}:{ce_cv}"
            stat = analytics_store.get_entity_stat(ce_et, ce_cv)
            node_map[ce_id] = GraphNodeResponse(
                id=ce_id,
                label=ce_cv,
                entity_type=ce_et,
                case_count=int(stat.get("case_count", 0)) if stat else 0,
                risk_score=float(stat.get("max_risk_score", 0)) if stat else 0,
                campaign_ids=(stat.get("campaign_ids") or []) if stat else [],
            )

        # Connect case entities that co-occur (they all share this case)
        entity_ids = list(node_map.keys())
        for i, eid_a in enumerate(entity_ids):
            for eid_b in entity_ids[i + 1 :]:
                edge_key = (min(eid_a, eid_b), max(eid_a, eid_b))
                if edge_key not in seen_edges:
                    seen_edges.add(edge_key)
                    edge_list.append(
                        GraphEdgeResponse(
                            source=eid_a,
                            target=eid_b,
                            weight=1,
                            case_ids=[seed],
                        )
                    )

        # Expand 1 hop from each case entity to find external connections
        if hops >= 1:
            for ce_et, ce_cv in case_entities:
                if len(node_map) >= limit:
                    break
                neighbors = analytics_store.get_entity_neighbors(ce_et, ce_cv, limit=min(10, limit))
                ce_id = f"{ce_et}:{ce_cv}"
                for nb in neighbors:
                    n_et = nb["entity_type"]
                    n_cv = nb["canonical_value"]
                    n_id = f"{n_et}:{n_cv}"
                    if type_filter and n_et not in type_filter:
                        continue
                    if n_id not in node_map:
                        nb_stat = analytics_store.get_entity_stat(n_et, n_cv)
                        node_map[n_id] = GraphNodeResponse(
                            id=n_id,
                            label=n_cv,
                            entity_type=n_et,
                            case_count=nb.get("case_count", 0),
                            risk_score=float(nb.get("risk_score", 0)),
                            campaign_ids=(nb_stat.get("campaign_ids") or []) if nb_stat else [],
                        )
                    edge_key = (min(ce_id, n_id), max(ce_id, n_id))
                    if edge_key not in seen_edges:
                        seen_edges.add(edge_key)
                        edge_list.append(
                            GraphEdgeResponse(
                                source=ce_id,
                                target=n_id,
                                weight=nb.get("shared_cases", 1),
                                case_ids=nb.get("shared_case_ids", []),
                            )
                        )

        nodes = list(node_map.values())[:limit]
        node_ids = {n.id for n in nodes}
        edges = [e for e in edge_list if e.source in node_ids and e.target in node_ids]
        return GraphPayloadResponse(nodes=nodes, edges=edges, node_count=len(nodes), edge_count=len(edges))

    # Entity seed — parse "entity_type:canonical_value"
    if ":" not in seed:
        return GraphPayloadResponse(nodes=[], edges=[], node_count=0, edge_count=0)

    seed_et, seed_cv = seed.split(":", 1)
    # Safety net: normalize in case the client sends a non-canonical type.
    # Once all data and UI use canonical types exclusively, this is a no-op.
    seed_et = normalize_entity_type(seed_et.strip())
    seed_cv = seed_cv.strip()
    seed_stat = analytics_store.get_entity_stat(seed_et, seed_cv)
    if not seed_stat:
        return GraphPayloadResponse(nodes=[], edges=[], node_count=0, edge_count=0)

    # Collect all nodes and edges via BFS
    node_map: dict[str, GraphNodeResponse] = {}
    edge_list: list[GraphEdgeResponse] = []
    seen_edges: set[tuple[str, str]] = set()

    seed_id = f"{seed_et}:{seed_cv}"
    node_map[seed_id] = GraphNodeResponse(
        id=seed_id,
        label=seed_cv,
        entity_type=seed_et,
        case_count=int(seed_stat.get("case_count", 0)),
        risk_score=float(seed_stat.get("max_risk_score", 0)),
        campaign_ids=seed_stat.get("campaign_ids") or [],
    )

    frontier = [(seed_et, seed_cv)]
    for _hop in range(hops):
        next_frontier: list[tuple[str, str]] = []
        for f_et, f_cv in frontier:
            f_id = f"{f_et}:{f_cv}"
            neighbors = analytics_store.get_entity_neighbors(f_et, f_cv, limit=limit)
            for nb in neighbors:
                n_et = nb["entity_type"]
                n_cv = nb["canonical_value"]
                n_id = f"{n_et}:{n_cv}"

                # Apply filters
                if type_filter and n_et not in type_filter:
                    continue
                nb_stat = (
                    analytics_store.get_entity_stat(n_et, n_cv)
                    if n_id not in node_map or risk_threshold is not None
                    else None
                )
                if risk_threshold is not None and nb_stat and float(nb_stat.get("max_risk_score", 0)) < risk_threshold:
                    continue

                if n_id not in node_map:
                    node_map[n_id] = GraphNodeResponse(
                        id=n_id,
                        label=n_cv,
                        entity_type=n_et,
                        case_count=nb.get("case_count", 0),
                        risk_score=float(nb.get("risk_score", 0)),
                        campaign_ids=(nb_stat.get("campaign_ids") or []) if nb_stat else [],
                    )
                    next_frontier.append((n_et, n_cv))

                edge_key = (min(f_id, n_id), max(f_id, n_id))
                if edge_key not in seen_edges:
                    seen_edges.add(edge_key)
                    edge_list.append(
                        GraphEdgeResponse(
                            source=f_id,
                            target=n_id,
                            weight=nb.get("shared_cases", 1),
                            case_ids=nb.get("shared_case_ids", []),
                        )
                    )

            if len(node_map) >= limit:
                break
        frontier = next_frontier
        if len(node_map) >= limit:
            break

    nodes = list(node_map.values())[:limit]
    node_ids = {n.id for n in nodes}
    edges = [e for e in edge_list if e.source in node_ids and e.target in node_ids]

    return GraphPayloadResponse(
        nodes=nodes,
        edges=edges,
        node_count=len(nodes),
        edge_count=len(edges),
    )


# ---------------------------------------------------------------------------
# S4-07  /api/intelligence/graph/export — render to PNG/SVG
# ---------------------------------------------------------------------------


@router.get("/graph/export")
def export_graph(
    seed: str = Query(..., description="Seed node ID"),
    fmt: str = Query("png", description="Export format: png or svg"),
    hops: int = Query(1, ge=1, le=3),
    analytics_store: AnalyticsStore = Depends(get_analytics_store),
) -> Any:
    """Export a graph subgraph as PNG or SVG image.

    Args:
        seed: Seed node identifier.
        fmt: Output format (png or svg).
        hops: Number of hops to expand.
        analytics_store: Injected AnalyticsStore.

    Returns:
        Image file response.
    """
    from fastapi.responses import Response

    # Use SQL-based neighbor expansion (same as /graph endpoint)
    if ":" not in seed:
        raise HTTPException(status_code=400, detail="Seed must be entity_type:canonical_value")
    seed_et, seed_cv = seed.split(":", 1)

    node_map: dict[str, dict[str, Any]] = {}
    edge_list: list[tuple[str, str, int]] = []

    seed_id = seed
    node_map[seed_id] = {"label": seed_cv}

    frontier = [(seed_et, seed_cv)]
    for _hop in range(hops):
        next_frontier: list[tuple[str, str]] = []
        for f_et, f_cv in frontier:
            f_id = f"{f_et}:{f_cv}"
            neighbors = analytics_store.get_entity_neighbors(f_et, f_cv, limit=500)
            for nb in neighbors:
                n_id = f"{nb['entity_type']}:{nb['canonical_value']}"
                if n_id not in node_map:
                    node_map[n_id] = {"label": nb["canonical_value"]}
                    next_frontier.append((nb["entity_type"], nb["canonical_value"]))
                edge_list.append((f_id, n_id, nb.get("shared_cases", 1)))
            if len(node_map) > 500:
                break
        frontier = next_frontier
        if len(node_map) > 500:
            break

    try:
        import io

        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import networkx as nx

        g = nx.Graph()
        for nid, data in node_map.items():
            g.add_node(nid, label=data.get("label", nid))
        for src, tgt, w in edge_list:
            if src in node_map and tgt in node_map:
                if g.has_edge(src, tgt):
                    g[src][tgt]["weight"] += w
                else:
                    g.add_edge(src, tgt, weight=w)

        fig, ax = plt.subplots(1, 1, figsize=(12, 8))
        pos = nx.spring_layout(g, seed=42)
        labels = {n: data.get("label", n)[:20] for n, data in g.nodes(data=True)}
        nx.draw(g, pos, ax=ax, labels=labels, node_size=300, font_size=7, with_labels=True)
        ax.set_title(f"Network Graph: {seed}")

        buf = io.BytesIO()
        if fmt == "svg":
            fig.savefig(buf, format="svg", bbox_inches="tight")
            plt.close(fig)
            buf.seek(0)
            return Response(content=buf.read(), media_type="image/svg+xml")
        else:
            fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
            plt.close(fig)
            buf.seek(0)
            return Response(content=buf.read(), media_type="image/png")
    except ImportError as err:
        raise HTTPException(status_code=501, detail="matplotlib not available for graph rendering") from err


# ---------------------------------------------------------------------------
# S4-13  /api/intelligence/timeline — multi-track temporal data
# ---------------------------------------------------------------------------


class TimelineTrack(CamelModel):
    """A single track in the multi-track timeline."""

    track: str
    data: list[dict[str, Any]] = Field(default_factory=list)


class TimelineResponse(CamelModel):
    """Multi-track timeline response."""

    tracks: list[TimelineTrack] = Field(default_factory=list)
    granularity: str = "week"


@router.get("/timeline", response_model=TimelineResponse)
def get_timeline(
    period: str = Query("90d", description="Period preset: 7d, 30d, 90d, quarter, year"),
    granularity: str = Query("week", description="Granularity: day, week, month"),
    analytics_store: AnalyticsStore = Depends(get_analytics_store),
) -> TimelineResponse:
    """Return multi-track temporal data for the timeline view.

    Tracks include case volume, new indicators, and campaign lifetimes.

    Args:
        period: Time window preset.
        granularity: Time granularity (day, week, month).
        analytics_store: Injected AnalyticsStore.

    Returns:
        Multi-track timeline response.
    """
    from datetime import date, timedelta

    mapping = {"7d": 7, "30d": 30, "90d": 90, "quarter": 91, "year": 365}
    days = mapping.get(period, 90)
    today = date.today()
    start = today - timedelta(days=days)

    # Map granularity to platform_kpis period_type
    pt = "weekly" if granularity == "week" else ("monthly" if granularity == "month" else "daily")
    kpis = analytics_store.list_platform_kpis(period_type=pt, start_date=start, end_date=today, limit=365)

    case_track = []
    indicator_track = []
    for k in kpis:
        period_label = str(k.get("period_start", ""))
        case_track.append({"period": period_label, "count": int(k.get("total_cases", 0))})
        indicator_track.append({"period": period_label, "count": int(k.get("new_indicators", 0))})

    tracks = [
        TimelineTrack(track="cases", data=case_track),
        TimelineTrack(track="indicators", data=indicator_track),
    ]

    return TimelineResponse(tracks=tracks, granularity=granularity)


# ---------------------------------------------------------------------------
# S4-14  Entity status management
# ---------------------------------------------------------------------------


class EntityStatusUpdateRequest(CamelModel):
    """Request to update entity status."""

    entity_type: str
    canonical_value: str
    status: str  # active | dormant | flagged | taken_down


@router.post("/entities/status")
def update_entity_status(
    payload: EntityStatusUpdateRequest,
    user: dict[str, str] = Depends(require_token),
    analytics_store: AnalyticsStore = Depends(get_analytics_store),
) -> dict[str, Any]:
    """Update an entity's status (Active/Dormant/Flagged/Taken Down).

    Args:
        payload: Entity identification and new status.
        user: Authenticated user.
        analytics_store: Injected AnalyticsStore.

    Returns:
        Confirmation dict.
    """
    valid_statuses = {"active", "dormant", "flagged", "taken_down"}
    if payload.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}")

    success = analytics_store.update_entity_status(
        entity_type=payload.entity_type,
        canonical_value=payload.canonical_value,
        status=payload.status,
    )
    if not success:
        raise HTTPException(status_code=404, detail="Entity not found")
    return {"entity_type": payload.entity_type, "canonical_value": payload.canonical_value, "status": payload.status}


# ---------------------------------------------------------------------------
# S4-15  Annotations CRUD
# ---------------------------------------------------------------------------


class AnnotationCreateRequest(CamelModel):
    """Request to create an annotation."""

    target_type: str  # entity | indicator | campaign | case
    target_id: str
    content: str


class AnnotationResponse(CamelModel):
    """Annotation response model."""

    annotation_id: str
    target_type: str
    target_id: str
    content: str
    author: str
    created_at: str | None = None
    updated_at: str | None = None

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _coerce_dt(cls, v: Any) -> str | None:
        if isinstance(v, datetime):
            return v.isoformat()
        return str(v) if v is not None else None


class AnnotationUpdateRequest(CamelModel):
    """Request to update an annotation."""

    content: str


@router.post("/annotations", response_model=AnnotationResponse)
def create_annotation(
    payload: AnnotationCreateRequest,
    user: dict[str, str] = Depends(require_token),
    store: AnnotationStore = Depends(get_annotation_store),
) -> AnnotationResponse:
    """Create a freeform annotation on an entity, indicator, campaign, or case.

    Args:
        payload: Annotation target and content.
        user: Authenticated user.
        store: Injected AnnotationStore.

    Returns:
        The created annotation.
    """
    valid_types = {"entity", "indicator", "campaign", "case"}
    if payload.target_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"target_type must be one of: {valid_types}")

    annotation_id = store.create_annotation(
        target_type=payload.target_type,
        target_id=payload.target_id,
        content=payload.content,
        author=user.get("username", "unknown"),
    )
    annotation = store.get_annotation(annotation_id)
    return AnnotationResponse(**annotation)


@router.get("/annotations", response_model=list[AnnotationResponse])
def list_annotations(
    target_type: str | None = Query(None, description="Filter by target type"),
    target_id: str | None = Query(None, description="Filter by target ID"),
    limit: int = Query(100, ge=1, le=500),
    store: AnnotationStore = Depends(get_annotation_store),
) -> list[AnnotationResponse]:
    """List annotations with optional filters.

    Args:
        target_type: Filter by target type.
        target_id: Filter by target ID.
        limit: Max results.
        store: Injected AnnotationStore.

    Returns:
        List of annotations.
    """
    items = store.list_annotations(target_type=target_type, target_id=target_id, limit=limit)
    return [AnnotationResponse(**i) for i in items]


@router.put("/annotations/{annotation_id}", response_model=AnnotationResponse)
def update_annotation(
    annotation_id: str,
    payload: AnnotationUpdateRequest,
    store: AnnotationStore = Depends(get_annotation_store),
) -> AnnotationResponse:
    """Update an existing annotation's content.

    Args:
        annotation_id: The annotation UUID.
        payload: New content.
        store: Injected AnnotationStore.

    Returns:
        Updated annotation.
    """
    success = store.update_annotation(annotation_id, content=payload.content)
    if not success:
        raise HTTPException(status_code=404, detail="Annotation not found")
    annotation = store.get_annotation(annotation_id)
    return AnnotationResponse(**annotation)


@router.delete("/annotations/{annotation_id}")
def delete_annotation(
    annotation_id: str,
    store: AnnotationStore = Depends(get_annotation_store),
) -> dict[str, bool]:
    """Delete an annotation.

    Args:
        annotation_id: The annotation UUID.
        store: Injected AnnotationStore.

    Returns:
        Confirmation dict.
    """
    success = store.delete_annotation(annotation_id)
    if not success:
        raise HTTPException(status_code=404, detail="Annotation not found")
    return {"deleted": True}


# ---------------------------------------------------------------------------
# S4-16 / S4-17  Bulk entity actions
# ---------------------------------------------------------------------------


class BulkActionRequest(CamelModel):
    """Request for bulk entity operations."""

    entity_ids: list[str] = Field(..., description="List of entity IDs (type:value format)")
    action: str = Field(..., description="Action: export | tag | status_update")
    tag: str | None = None
    status: str | None = None


class BulkActionResult(CamelModel):
    """Result of a bulk operation."""

    processed: int = 0
    failed: int = 0
    errors: list[str] = Field(default_factory=list)


@router.post("/entities/bulk", response_model=BulkActionResult)
def bulk_entity_action(
    payload: BulkActionRequest,
    user: dict[str, str] = Depends(require_token),
    analytics_store: AnalyticsStore = Depends(get_analytics_store),
) -> BulkActionResult:
    """Perform a bulk action on multiple entities.

    Supports: export (returns count), tag, status_update.

    Args:
        payload: Bulk action specification.
        user: Authenticated user.
        analytics_store: Injected AnalyticsStore.

    Returns:
        Summary of processed and failed items.
    """
    valid_actions = {"export", "tag", "status_update"}
    if payload.action not in valid_actions:
        raise HTTPException(status_code=400, detail=f"Invalid action. Must be one of: {valid_actions}")

    processed = 0
    failed = 0
    errors: list[str] = []

    for eid in payload.entity_ids:
        parts = eid.split(":", 1)
        if len(parts) != 2:
            failed += 1
            errors.append(f"Invalid entity ID format: {eid}")
            continue

        entity_type, canonical_value = parts

        if payload.action == "status_update" and payload.status:
            success = analytics_store.update_entity_status(
                entity_type=entity_type,
                canonical_value=canonical_value,
                status=payload.status,
            )
            if success:
                processed += 1
            else:
                failed += 1
                errors.append(f"Entity not found: {eid}")
        elif payload.action in ("export", "tag"):
            # export and tag are bookkeeping — count as processed
            processed += 1
        else:
            failed += 1
            errors.append(f"Missing status for status_update on {eid}")

    return BulkActionResult(processed=processed, failed=failed, errors=errors[:20])


# ---------------------------------------------------------------------------
# S5-01  /api/intelligence/graph/temporal — temporal graph animation snapshots
# ---------------------------------------------------------------------------


class TemporalSnapshotResponse(CamelModel):
    """Single frame in a temporal graph animation."""

    date: str
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    node_count: int = 0
    edge_count: int = 0


@router.get("/graph/temporal", response_model=list[TemporalSnapshotResponse])
def get_temporal_graph(
    seed: str = Query(..., description="Seed node ID"),
    hops: int = Query(1, ge=1, le=3, description="Number of hops"),
    analytics_store: AnalyticsStore = Depends(get_analytics_store),
) -> list[TemporalSnapshotResponse]:
    """Return timestamped graph snapshots for animation (F-41).

    Generates cumulative graph states at monthly intervals so the frontend
    can animate graph growth over time with a date slider.

    Args:
        seed: Seed node identifier.
        hops: Number of BFS hops.
        analytics_store: Injected AnalyticsStore.

    Returns:
        Ordered list of temporal snapshots.
    """
    from i4g.services.graph_service import GraphService

    all_entities = analytics_store.list_entity_stats(limit=10000)

    adjacency: dict[str, list[str]] = {}
    entity_meta: dict[str, dict[str, Any]] = {}
    timestamps: dict[str, str] = {}

    for e in all_entities:
        eid = f"{e['entity_type']}:{e['canonical_value']}"
        adjacency[eid] = [f"case-{i}" for i in range(int(e.get("case_count", 0)))]
        entity_meta[eid] = {
            "entity_type": e.get("entity_type", "unknown"),
            "label": str(e.get("canonical_value", eid)),
            "case_count": int(e.get("case_count", 0)),
            "risk_score": float(e.get("max_risk_score", 0)),
        }
        first_seen = e.get("first_seen_at")
        if first_seen:
            ts = str(first_seen)
            if "T" not in ts:
                ts += "T00:00:00"
            timestamps[eid] = ts

    graph_service = GraphService(adjacency, entity_meta)
    snapshots = graph_service.get_temporal_snapshots(timestamps)

    return [TemporalSnapshotResponse(**s) for s in snapshots]


# ---------------------------------------------------------------------------
# S5-02 / S5-03  /api/intelligence/graph/clusters — community detection
# ---------------------------------------------------------------------------


class ClusterResponse(CamelModel):
    """Detected community/cluster in the entity graph."""

    id: str
    size: int
    members: list[str]
    density: float = 0.0
    avg_risk_score: float = 0.0
    entity_types: dict[str, int] = Field(default_factory=dict)


@router.get("/graph/clusters", response_model=list[ClusterResponse])
def get_graph_clusters(
    min_size: int = Query(3, ge=2, description="Minimum cluster size"),
    resolution: float = Query(1.0, ge=0.1, le=5.0, description="Louvain resolution"),
    analytics_store: AnalyticsStore = Depends(get_analytics_store),
) -> list[ClusterResponse]:
    """Detect communities in the entity co-occurrence graph (F-42).

    Uses Louvain community detection to find dense subgraphs. Higher
    resolution values produce more, smaller clusters.

    Args:
        min_size: Minimum cluster size to return.
        resolution: Louvain resolution parameter.
        analytics_store: Injected AnalyticsStore.

    Returns:
        List of detected clusters sorted by size descending.
    """
    from i4g.services.graph_service import GraphService

    all_entities = analytics_store.list_entity_stats(limit=10000)

    adjacency: dict[str, list[str]] = {}
    entity_meta: dict[str, dict[str, Any]] = {}
    for e in all_entities:
        eid = f"{e['entity_type']}:{e['canonical_value']}"
        adjacency[eid] = [f"case-{i}" for i in range(int(e.get("case_count", 0)))]
        entity_meta[eid] = {
            "entity_type": e.get("entity_type", "unknown"),
            "label": str(e.get("canonical_value", eid)),
            "case_count": int(e.get("case_count", 0)),
            "risk_score": float(e.get("max_risk_score", 0)),
        }

    graph_service = GraphService(adjacency, entity_meta)
    clusters = graph_service.detect_clusters(min_size=min_size, resolution=resolution)
    return [ClusterResponse(**c) for c in clusters]


# ---------------------------------------------------------------------------
# S5-04 / S5-05  Watchlist endpoints (F-43)
# ---------------------------------------------------------------------------


class WatchlistItemRequest(CamelModel):
    """Request to add or update a watchlist item."""

    entity_type: str
    canonical_value: str
    alert_on_new_case: bool = True
    alert_on_loss_increase: bool = False
    loss_threshold: float | None = None
    note: str | None = None


class WatchlistItemResponse(CamelModel):
    """Watchlist item representation."""

    watchlist_id: str
    entity_type: str
    canonical_value: str
    alert_on_new_case: bool = True
    alert_on_loss_increase: bool = False
    loss_threshold: float | None = None
    note: str | None = None
    created_by: str = "system"
    created_at: str | None = None
    updated_at: str | None = None

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _coerce_dt(cls, v: Any) -> str | None:
        if isinstance(v, datetime):
            return v.isoformat()
        return v


class WatchlistListResponse(CamelModel):
    """Paginated watchlist items."""

    items: list[WatchlistItemResponse]
    count: int
    limit: int
    offset: int


class WatchlistUpdateRequest(CamelModel):
    """Request to update watchlist alert conditions."""

    alert_on_new_case: bool | None = None
    alert_on_loss_increase: bool | None = None
    loss_threshold: float | None = None
    note: str | None = None


class WatchlistAlertResponse(CamelModel):
    """Watchlist alert representation."""

    alert_id: str
    watchlist_id: str
    alert_type: str
    message: str
    is_read: bool = False
    data: dict[str, Any] | None = None
    created_at: str | None = None

    @field_validator("created_at", mode="before")
    @classmethod
    def _coerce_dt(cls, v: Any) -> str | None:
        if isinstance(v, datetime):
            return v.isoformat()
        return v


@router.post("/watchlist", response_model=WatchlistItemResponse, status_code=201)
def add_to_watchlist(
    payload: WatchlistItemRequest,
    user: dict[str, str] = Depends(require_token),
    store: WatchlistStore = Depends(get_watchlist_store),
) -> WatchlistItemResponse:
    """Pin an entity to the watchlist.

    Args:
        payload: Watchlist item details.
        user: Authenticated user.
        store: Injected WatchlistStore.

    Returns:
        Created watchlist item.
    """
    existing = store.find_by_entity(payload.entity_type, payload.canonical_value)
    if existing:
        raise HTTPException(status_code=409, detail="Entity is already on the watchlist")

    wid = store.add_item(
        entity_type=payload.entity_type,
        canonical_value=payload.canonical_value,
        alert_on_new_case=payload.alert_on_new_case,
        alert_on_loss_increase=payload.alert_on_loss_increase,
        loss_threshold=payload.loss_threshold,
        note=payload.note,
        created_by=user.get("email", "system"),
    )
    item = store.get_item(wid)
    if not item:
        raise HTTPException(status_code=500, detail="Failed to create watchlist item")
    return WatchlistItemResponse.model_validate(item)


@router.get("/watchlist", response_model=WatchlistListResponse)
def list_watchlist(
    entity_type: str | None = Query(None, description="Filter by entity type"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: dict[str, str] = Depends(require_token),
    store: WatchlistStore = Depends(get_watchlist_store),
) -> WatchlistListResponse:
    """List watchlist items for the current user.

    Args:
        entity_type: Optional entity type filter.
        limit: Page size.
        offset: Pagination offset.
        user: Authenticated user.
        store: Injected WatchlistStore.

    Returns:
        Paginated watchlist items.
    """
    items = store.list_items(
        created_by=user.get("email"),
        entity_type=entity_type,
        limit=limit,
        offset=offset,
    )
    total = store.count_items(created_by=user.get("email"))
    return WatchlistListResponse(
        items=[WatchlistItemResponse.model_validate(i) for i in items],
        count=total,
        limit=limit,
        offset=offset,
    )


@router.put("/watchlist/{watchlist_id}", response_model=WatchlistItemResponse)
def update_watchlist_item(
    watchlist_id: str,
    payload: WatchlistUpdateRequest,
    user: dict[str, str] = Depends(require_token),
    store: WatchlistStore = Depends(get_watchlist_store),
) -> WatchlistItemResponse:
    """Update alert conditions for a watchlist item.

    Args:
        watchlist_id: Watchlist item ID.
        payload: Fields to update.
        user: Authenticated user.
        store: Injected WatchlistStore.

    Returns:
        Updated watchlist item.
    """
    existing = store.get_item(watchlist_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    if existing.get("created_by") != user.get("email") and user.get("role") != Role.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized to modify this item")

    store.update_item(
        watchlist_id,
        alert_on_new_case=payload.alert_on_new_case,
        alert_on_loss_increase=payload.alert_on_loss_increase,
        loss_threshold=payload.loss_threshold,
        note=payload.note,
    )
    item = store.get_item(watchlist_id)
    return WatchlistItemResponse.model_validate(item)


@router.delete("/watchlist/{watchlist_id}")
def remove_from_watchlist(
    watchlist_id: str,
    user: dict[str, str] = Depends(require_token),
    store: WatchlistStore = Depends(get_watchlist_store),
) -> dict[str, bool]:
    """Remove an entity from the watchlist.

    Args:
        watchlist_id: Watchlist item ID.
        user: Authenticated user.
        store: Injected WatchlistStore.

    Returns:
        Deletion confirmation.
    """
    existing = store.get_item(watchlist_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    if existing.get("created_by") != user.get("email") and user.get("role") != Role.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized to remove this item")

    store.remove_item(watchlist_id)
    return {"deleted": True}


@router.get("/watchlist/alerts", response_model=list[WatchlistAlertResponse])
def list_watchlist_alerts(
    unread_only: bool = Query(False, description="Only return unread alerts"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: dict[str, str] = Depends(require_token),
    store: WatchlistStore = Depends(get_watchlist_store),
) -> list[WatchlistAlertResponse]:
    """List watchlist alerts.

    Args:
        unread_only: Only return unread alerts.
        limit: Page size.
        offset: Pagination offset.
        user: Authenticated user.
        store: Injected WatchlistStore.

    Returns:
        List of alerts.
    """
    alerts = store.list_alerts(unread_only=unread_only, limit=limit, offset=offset)
    return [WatchlistAlertResponse.model_validate(a) for a in alerts]


@router.post("/watchlist/alerts/{alert_id}/read")
def mark_alert_as_read(
    alert_id: str,
    store: WatchlistStore = Depends(get_watchlist_store),
) -> dict[str, bool]:
    """Mark a watchlist alert as read.

    Args:
        alert_id: Alert ID.
        store: Injected WatchlistStore.

    Returns:
        Confirmation.
    """
    success = store.mark_alert_read(alert_id)
    if not success:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"marked_read": True}


@router.post("/watchlist/alerts/read-all")
def mark_all_alerts_read(
    store: WatchlistStore = Depends(get_watchlist_store),
) -> dict[str, int]:
    """Mark all watchlist alerts as read.

    Args:
        store: Injected WatchlistStore.

    Returns:
        Count of alerts marked.
    """
    count = store.mark_all_read()
    return {"marked_read": count}


# ---------------------------------------------------------------------------
# S5-17 / S5-18  Embeddable chart share tokens
# ---------------------------------------------------------------------------


class ChartShareRequest(CamelModel):
    """Request to create a shareable chart token."""

    chart_type: str
    chart_config: dict
    expires_in_hours: int = 72


class ChartShareResponse(CamelModel):
    """Shareable chart token with embed URL template."""

    token_id: str
    chart_type: str
    chart_config: dict
    expires_at: str
    embed_url: str


@router.post("/charts/share", response_model=ChartShareResponse, status_code=201)
def create_chart_share_token(
    body: ChartShareRequest,
    user: str = Depends(require_token),
) -> ChartShareResponse:
    """Create a time-limited shareable token for a chart configuration.

    Args:
        body: Chart config and expiry.
        user: Authenticated user.

    Returns:
        Token details with embed URL.
    """
    import uuid
    from datetime import UTC, datetime, timedelta

    from i4g.store.sql import chart_share_tokens
    from i4g.store.sql import session_factory as build_sql_session_factory

    sf = build_sql_session_factory()
    session = sf()
    try:
        token_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        expires_at = now + timedelta(hours=body.expires_in_hours)

        session.execute(
            chart_share_tokens.insert().values(
                token_id=token_id,
                chart_type=body.chart_type,
                chart_config=body.chart_config,
                created_by=user,
                expires_at=expires_at,
                created_at=now,
            )
        )
        session.commit()

        return ChartShareResponse(
            token_id=token_id,
            chart_type=body.chart_type,
            chart_config=body.chart_config,
            expires_at=expires_at.isoformat(),
            embed_url=f"/api/intelligence/charts/{token_id}/embed",
        )
    finally:
        session.close()


@router.get("/charts/{token_id}/embed")
def get_embedded_chart(token_id: str) -> dict:
    """Retrieve chart configuration for a shared embed token.

    This endpoint is public (no auth required) — the token itself
    acts as a capability. Expired tokens return 410 Gone.

    Args:
        token_id: Chart share token ID.

    Returns:
        Chart type and configuration for rendering.
    """
    from datetime import UTC, datetime

    import sqlalchemy as sa

    from i4g.store.sql import chart_share_tokens
    from i4g.store.sql import session_factory as build_sql_session_factory

    sf = build_sql_session_factory()
    session = sf()
    try:
        row = session.execute(sa.select(chart_share_tokens).where(chart_share_tokens.c.token_id == token_id)).first()

        if not row:
            raise HTTPException(status_code=404, detail="Token not found")

        if row.expires_at and row.expires_at < datetime.now(UTC):
            raise HTTPException(status_code=410, detail="Token has expired")

        return {
            "chartType": row.chart_type,
            "chartConfig": row.chart_config,
            "expiresAt": row.expires_at.isoformat() if row.expires_at else None,
        }
    finally:
        session.close()
