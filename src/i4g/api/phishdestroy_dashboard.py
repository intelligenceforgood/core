"""FastAPI router exposing the PhishDestroy dashboard endpoints."""

import logging

from fastapi import APIRouter, Depends

from i4g.api.auth import require_token
from i4g.api.camel import CamelModel
from i4g.services.factories import (
    build_actor_identity_edge_store,
    build_actor_identity_store,
    build_domain_discovery_store,
    build_financial_damage_store,
    build_threat_actor_store,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/phishdestroy/dashboard",
    tags=["phishdestroy", "dashboard"],
    dependencies=[Depends(require_token)],
)


class DashboardStatsResponse(CamelModel):
    total_actors: int
    active_domains: int


@router.get("/stats", response_model=DashboardStatsResponse)
def get_dashboard_stats() -> DashboardStatsResponse:
    """Get high-level dashboard stats."""
    actor_store = build_threat_actor_store()
    discovery_store = build_domain_discovery_store()

    total_actors = actor_store.count_actors()
    active_domains = discovery_store.count_recent_matches()

    return DashboardStatsResponse(
        total_actors=total_actors,
        active_domains=active_domains,
    )


class ThreatActorItem(CamelModel):
    name: str
    aliases: list[str]
    stolen_amount: float
    domains: list[str]
    status: str


@router.get("/actors", response_model=list[ThreatActorItem])
def get_dashboard_actors() -> list[ThreatActorItem]:
    """Get the list of active threats and threat actors."""
    actor_store = build_threat_actor_store()
    identity_store = build_actor_identity_store()
    damage_store = build_financial_damage_store()

    actors = actor_store.list_actors(limit=50)
    results = []

    for actor in actors:
        actor_id = actor["actor_id"]
        campaign_id = actor.get("campaign_id")

        # Aliases
        identities = identity_store.list_by_actor(actor_id)
        aliases = [ident["handle"] for ident in identities if ident.get("handle")]

        # Stolen Amount
        stolen_amount = 0.0
        if campaign_id:
            damage_totals = damage_store.totals_by_currency(campaign_id)
            stolen_amount = float(sum(curr_data["claimed"] for curr_data in damage_totals.values()))

        # Status
        status = "active"

        results.append(
            ThreatActorItem(
                name=actor.get("display_name", "Unknown"),
                aliases=aliases,
                stolen_amount=stolen_amount,
                domains=[],  # Domain tracking directly per actor via discoveries requires additional mapping
                status=status,
            )
        )

    return results


class GraphNode(CamelModel):
    id: str
    group: int
    label: str


class GraphLink(CamelModel):
    source: str
    target: str
    value: int


class GraphResponse(CamelModel):
    nodes: list[GraphNode]
    links: list[GraphLink]


@router.get("/graph", response_model=GraphResponse)
def get_dashboard_graph() -> GraphResponse:
    """Get the relationship graph nodes and links."""
    identity_store = build_actor_identity_store()
    edge_store = build_actor_identity_edge_store()

    identities = identity_store.list_all_identities(limit=1000)
    edges = edge_store.list_all_edges(limit=2000)

    nodes = []
    for ident in identities:
        nodes.append(
            GraphNode(
                id=ident["identity_id"],
                group=1,
                label=ident.get("handle") or "Unknown",
            )
        )

    links = []
    for edge in edges:
        links.append(
            GraphLink(
                source=edge["source_identity_id"],
                target=edge["target_identity_id"],
                value=int(edge.get("weight") or 1),
            )
        )

    return GraphResponse(nodes=nodes, links=links)
