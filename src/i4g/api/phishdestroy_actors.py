"""FastAPI router exposing the PhishDestroy actors API."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Header, HTTPException, Query

from i4g.api.auth import require_token
from i4g.api.camel import CamelModel
from i4g.api.roles import Role, has_role
from i4g.services.factories import (
    build_actor_identity_edge_store,
    build_actor_identity_store,
    build_brand_impersonation_store,
    build_chat_session_store,
    build_financial_damage_store,
    build_leak_record_store,
    build_threat_actor_store,
)
from i4g.store import sql as sql_schema
from i4g.store.sql import session_factory

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/actors",
    tags=["actors"],
    dependencies=[Depends(require_token)],
)


def _log_pii_access(username: str, resource_type: str, resource_id: str, reason: str) -> None:
    """Log an audit entry for PII access."""
    now = datetime.now(UTC)
    with session_factory() as session:
        session.execute(
            sa.insert(sql_schema.audit_log).values(
                audit_id=str(uuid.uuid4()),
                actor=username,
                action="read_pii",
                resource_type=resource_type,
                resource_id=resource_id,
                created_at=now,
                payload={"reason": reason},
            )
        )
        session.commit()


class ThreatActorRow(CamelModel):
    actor_id: str
    display_name: str
    role: str | None = None
    campaign_id: str | None = None
    real_name: str | None = None
    confidence: float | None = None
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    metadata: dict[str, Any] | None = None


class ActorListResponse(CamelModel):
    items: list[ThreatActorRow]
    total: int
    limit: int
    offset: int


@router.get("", response_model=ActorListResponse)
def list_actors(
    role: str | None = None,
    campaign_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    min_confidence: float | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    x_reason: str | None = Header(default=None),
    reason: str | None = Query(default=None),
    user: dict[str, str] = Depends(require_token),
) -> ActorListResponse:
    """List threat actors with filtering."""
    store = build_threat_actor_store()

    # We fetch slightly more to know if there's a next page or just return the items.
    # The requirement didn't specify total count but we return total=len for simplicity
    # unless we want to run a count query. We'll just return what we have.
    items = store.list_actors(
        role=role,
        campaign_id=campaign_id,
        since=since,
        until=until,
        min_confidence=min_confidence,
        limit=limit,
        offset=offset,
    )

    # Apply PII redaction
    is_senior = has_role(user.get("role", ""), Role.SENIOR_ANALYST.value)
    final_reason = reason or x_reason

    has_pii = any(item.get("real_name") for item in items)
    if has_pii and is_senior:
        if not final_reason:
            raise HTTPException(status_code=400, detail="Reason code required for PII access")

        # Log access for each actor where real_name is populated
        for item in items:
            if item.get("real_name"):
                _log_pii_access(user["username"], "threat_actor", item["actor_id"], final_reason)

    # Redact if not authorized
    if not is_senior:
        for item in items:
            item["real_name"] = None

    return ActorListResponse(
        items=[ThreatActorRow(**r) for r in items],
        total=len(items),
        limit=limit,
        offset=offset,
    )


class ActorIdentityEdge(CamelModel):
    source_identity_id: str
    target_identity_id: str
    edge_type: str


class ActorIdentityRow(CamelModel):
    identity_id: str
    platform: str
    handle: str
    metadata: dict[str, Any] | None = None


class LeakRecordRow(CamelModel):
    leak_id: str
    source_breach: str
    password_cleartext: str | None = None
    email: str | None = None


class ChatSessionRow(CamelModel):
    session_id: str
    transcript: str | None = None
    # other fields...


class ActorDetailResponse(CamelModel):
    actor: ThreatActorRow
    identities: list[ActorIdentityRow]
    edges: list[ActorIdentityEdge]
    leaks: list[LeakRecordRow]
    chats: list[dict[str, Any]]
    damage: list[dict[str, Any]]
    brands: list[dict[str, Any]]
    linked_campaigns: list[str]


@router.get("/{actor_id}", response_model=ActorDetailResponse)
def get_actor(
    actor_id: str,
    x_reason: str | None = Header(default=None),
    reason: str | None = Query(default=None),
    user: dict[str, str] = Depends(require_token),
) -> ActorDetailResponse:
    """Get full actor detail panel."""
    actor_store = build_threat_actor_store()
    actor_row = actor_store.get(actor_id)
    if not actor_row:
        raise HTTPException(status_code=404, detail="Actor not found")

    identity_store = build_actor_identity_store()
    identities = identity_store.list_by_actor(actor_id)

    edge_store = build_actor_identity_edge_store()
    edges = []
    for ident in identities:
        neighbors = edge_store.neighbors(ident["identity_id"])
        edges.extend(neighbors)

    # Gather related records
    leak_store = build_leak_record_store()
    leaks = []
    for ident in identities:
        ident_leaks = leak_store.list_by_identity(ident["identity_id"])
        leaks.extend(ident_leaks)

    chat_store = build_chat_session_store()
    chats = chat_store.list_by_actor(actor_id)

    damage_store = build_financial_damage_store()
    campaign_id = actor_row.get("campaign_id")
    damage = damage_store.list_by_campaign(campaign_id) if campaign_id else []

    brand_store = build_brand_impersonation_store()
    brands = brand_store.list_by_campaign(campaign_id) if campaign_id else []

    # Filter PII
    is_senior = has_role(user.get("role", ""), Role.SENIOR_ANALYST.value)
    final_reason = reason or x_reason

    logs_to_emit = []

    if actor_row.get("real_name"):
        if is_senior:
            logs_to_emit.append(("threat_actor", actor_id))
        else:
            actor_row["real_name"] = None

    for leak in leaks:
        if leak.get("password_cleartext"):
            if is_senior:
                logs_to_emit.append(("leak_record", leak["leak_id"]))
            else:
                leak["password_cleartext"] = None

    for chat in chats:
        if chat.get("transcript") or chat.get("messages"):
            if is_senior:
                logs_to_emit.append(("chat_session", chat["session_id"]))
            else:
                chat["transcript"] = None
                if "messages" in chat:
                    chat["messages"] = None

    if logs_to_emit:
        if not final_reason:
            raise HTTPException(status_code=400, detail="Reason code required for PII access")
        for r_type, r_id in logs_to_emit:
            _log_pii_access(user["username"], r_type, r_id, final_reason)

    return ActorDetailResponse(
        actor=ThreatActorRow(**actor_row),
        identities=[ActorIdentityRow(**i) for i in identities],
        edges=[ActorIdentityEdge(**e) for e in edges],
        leaks=[LeakRecordRow(**leak) for leak in leaks],
        chats=chats,
        damage=damage,
        brands=brands,
        linked_campaigns=[campaign_id] if campaign_id else [],
    )
