"""Case CRUD endpoints for the analyst console and programmatic integrations.

Provides list, detail, create, update, batch entity/indicator, GDPR
export and GDPR delete for the ``/cases`` namespace.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

import sqlalchemy as sa
from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from i4g.api.auth import require_role, require_token
from i4g.api.camel import CamelModel
from i4g.api.response_models import CasesListResponse
from i4g.services.factories import build_retention_service, build_review_store
from i4g.store import sql as sql_schema
from i4g.store.sql import dialect_insert, session_factory as build_sql_session_factory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cases", tags=["cases"], dependencies=[Depends(require_token)])

# --- Schemas ---


class CaseArtifact(CamelModel):
    id: str
    type: str = Field(..., description="Type of artifact (document, image, etc.)")
    name: str = Field(..., description="Display name of the artifact")
    url: str | None = Field(None, description="Link to the artifact content")
    metadata: dict[str, Any] = Field(default_factory=dict)


class CaseTimelineEvent(CamelModel):
    id: str
    timestamp: datetime
    description: str
    actor: str | None = Field(None, description="User or system actor")
    type: str = Field(..., description="Type of event (comment, status_change, alert)")


class CaseGraphNode(CamelModel):
    """Single node in the case investigation graph."""

    id: str
    label: str
    type: str
    data: dict[str, Any] = Field(default_factory=dict)


class CaseGraphLink(CamelModel):
    """Directed edge in the case investigation graph."""

    source: str
    target: str
    relation: str


# Enum-like types matching SDK Zod schemas
CaseStatus = Literal["new", "queued", "in_review", "awaiting_input", "closed", "accepted", "rejected"]
CasePriority = Literal["critical", "high", "medium", "low"]


class CaseDetail(CamelModel):
    """Detailed view of a case for the investigation workspace."""

    id: str
    title: str
    status: CaseStatus
    priority: CasePriority
    assignee: str | None = None
    updated_at: str | None = None
    queue: str | None = None
    tags: list[str] = Field(default_factory=list)
    progress: int | None = None
    due_at: str | None = None
    classification: dict[str, Any] | None = Field(
        None,
        description="Fraud classification result (intent, channel, techniques, actions, persona, risk_score, etc.)",
    )
    description: str = Field("", description="Detailed narrative of the case")
    artifacts: list[CaseArtifact] = Field(default_factory=list)
    timeline: list[CaseTimelineEvent] = Field(default_factory=list)
    graph_nodes: list[CaseGraphNode] = Field(default_factory=list)
    graph_links: list[CaseGraphLink] = Field(default_factory=list)


# --- Request models (write endpoints) ---


class CreateCaseRequest(BaseModel):
    """Payload for ``POST /cases``."""

    dataset: str = Field(..., description="Dataset label, e.g. 'ssi'.")
    source_type: str = Field("ssi_investigation", description="Source system identifier.")
    source_url: str | None = Field(None, description="URL of the investigated site.")
    title: str | None = Field(None, description="Human-readable case title.")
    classification_result: dict[str, Any] | None = Field(None, description="Taxonomy classification result.")
    risk_score: float | None = Field(None, description="Numeric risk score (0-100).")
    metadata: dict[str, Any] | None = Field(None, description="Arbitrary metadata dict.")


class CreateCaseResponse(CamelModel):
    """Response for ``POST /cases``."""

    case_id: str
    created: bool = True


class UpdateCaseRequest(BaseModel):
    """Payload for ``PATCH /cases/{case_id}``."""

    classification_result: dict[str, Any] | None = None
    classification_status: str | None = None
    risk_score: float | None = None
    status: str | None = None
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None


class TimelineEventRequest(BaseModel):
    """Payload for a single timeline event in ``POST /cases/{case_id}/timeline``."""

    description: str = Field(..., description="Human-readable event description.")
    actor: str = Field("system", description="User or system actor (e.g. 'ssi-agent').")
    type: str = Field(..., description="Event type key (e.g. 'investigation_submitted').")
    timestamp: datetime | None = Field(None, description="Event timestamp; defaults to now.")


class BatchTimelineRequest(BaseModel):
    """Payload for ``POST /cases/{case_id}/timeline``."""

    events: list[TimelineEventRequest]


class BatchTimelineResponse(CamelModel):
    """Response for timeline event batch creation."""

    case_id: str
    created: int


class EntityItem(BaseModel):
    """Single entity in a batch-create request."""

    entity_type: str
    canonical_value: str
    raw_value: str | None = None
    confidence: float = 0.9
    metadata: dict[str, Any] | None = None


class BatchEntitiesRequest(BaseModel):
    """Payload for ``POST /cases/{case_id}/entities/batch``."""

    entities: list[EntityItem]


class BatchEntitiesResponse(CamelModel):
    """Response for entity batch creation."""

    case_id: str
    created: int


class IndicatorItem(BaseModel):
    """Single indicator in a batch-create request."""

    category: str
    type: str
    number: str
    item: str | None = None
    status: str = "active"
    confidence: float = 0.0
    dataset: str | None = None
    metadata: dict[str, Any] | None = None


class BatchIndicatorsRequest(BaseModel):
    """Payload for ``POST /cases/{case_id}/indicators/batch``."""

    indicators: list[IndicatorItem]


class BatchIndicatorsResponse(CamelModel):
    """Response for indicator batch creation."""

    case_id: str
    created: int


# --- Data ---
# Mock case data moved to i4g.fixtures.sample_cases (E26).
# The get_case() endpoint now returns 404 for cases not in the DB.


@router.get("", summary="List active cases", response_model=CasesListResponse)
def list_cases(
    limit: int = 50,
    status: str | None = None,
    priority: str | None = None,
    queue: str | None = None,
    due_date: str | None = None,
) -> dict[str, Any]:
    """Return summaries for the Cases console view (from Live DB)."""
    store = build_review_store()
    return store.get_dashboard_summary(limit=limit, status=status, priority=priority, queue=queue, due_date=due_date)


@router.get("/{case_id}", response_model=CaseDetail, response_model_exclude_unset=True, summary="Get case details")
def get_case(case_id: str) -> CaseDetail:
    """Get full details for a specific case (Live DB)."""
    store = build_review_store()
    data = store.get_extended_case(case_id)

    if not data:
        raise HTTPException(status_code=404, detail="Case not found")

    # DB Mapping
    props = data.get("metadata") or {}
    if isinstance(props, str):
        try:
            props = json.loads(props)
        except json.JSONDecodeError:
            props = {}

    # Timeline
    timeline_events = []
    for action in data.get("timeline", []):
        ts_str = action.get("created_at")
        ts = datetime.fromisoformat(ts_str) if ts_str else datetime.now(timezone.utc)
        raw_payload = action.get("payload")
        description = _format_timeline_description(action["action"], raw_payload)
        timeline_events.append(
            CaseTimelineEvent(
                id=action["action_id"],
                timestamp=ts,
                description=description,
                actor=action["actor"],
                type=action["action"],
            )
        )

    # Graph
    nodes = []
    links = []
    entities = data.get("entities")
    if entities:
        if isinstance(entities, str):
            try:
                entities = json.loads(entities)
            except json.JSONDecodeError:
                entities = {}

        if isinstance(entities, dict):
            unique_ids = set()
            for k, vals in entities.items():
                if isinstance(vals, list):
                    for v in vals:
                        nid = f"{k}:{v}"
                        if nid not in unique_ids:
                            nodes.append(CaseGraphNode(id=nid, label=str(v), type=k))
                            unique_ids.add(nid)

    # Tags
    tags = data.get("rq_tags")
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except json.JSONDecodeError:
            tags = []
    elif not tags:
        tags = []

    # Artifacts — merge metadata.files with uploaded source_documents
    artifacts = []
    files_list = props.get("files")
    if isinstance(files_list, list):
        for idx, f in enumerate(files_list):
            if isinstance(f, dict):
                artifacts.append(
                    CaseArtifact(
                        id=f"art-{idx}",
                        type=f.get("type", "document"),
                        name=f.get("name", "Unknown File"),
                        url=f.get("url"),
                        metadata={"size": f.get("size")},
                    )
                )

    # Also include evidence files from source_documents table
    sf = build_sql_session_factory()
    with sf() as session:
        doc_rows = session.execute(
            sa.select(
                sql_schema.source_documents.c.document_id,
                sql_schema.source_documents.c.title,
                sql_schema.source_documents.c.mime_type,
                sql_schema.source_documents.c.source_url,
            ).where(sql_schema.source_documents.c.case_id == case_id)
        ).fetchall()
        for row in doc_rows:
            mapping = row._mapping
            doc_id = str(mapping["document_id"])
            doc_title = mapping.get("title") or doc_id[:12]
            mime = mapping.get("mime_type") or "application/octet-stream"
            artifact_type = _mime_to_artifact_type(mime)
            artifacts.append(
                CaseArtifact(
                    id=f"doc-{doc_id}",
                    type=artifact_type,
                    name=doc_title,
                    url=f"/cases/{case_id}/evidence/{doc_id}",
                    metadata={"mime_type": mime, "source_url": mapping.get("source_url")},
                )
            )

        # SSI investigation PDF report (if this case originated from SSI)
        # Prefer the scan_id from site_scans (authoritative — created by core at
        # trigger time) over the metadata value which may diverge if the Cloud
        # Run Job received a different investigation_id.
        ssi_inv_id = None
        if data.get("source_type") == "ssi_investigation" or props.get("ssi_investigation_id"):
            scan_row = session.execute(
                sa.select(sql_schema.site_scans.c.scan_id).where(
                    sql_schema.site_scans.c.case_id == case_id
                ).order_by(sql_schema.site_scans.c.created_at.desc()).limit(1)
            ).scalar()
            ssi_inv_id = str(scan_row) if scan_row else props.get("ssi_investigation_id")
    if ssi_inv_id:
        # Drop report.pdf from the source_documents list — it is the same file
        # served by the prominent "Investigation Report (PDF)" entry below.
        # It remains in source_documents so the download bundle still includes it.
        artifacts = [a for a in artifacts if a.name != "report.pdf"]
        artifacts.append(
            CaseArtifact(
                id=f"ssi-report-{ssi_inv_id}",
                type="report",
                name="Investigation Report (PDF)",
                url=f"/ssi/report/{ssi_inv_id}?action=inline",
                metadata={"mime_type": "application/pdf", "source": "ssi"},
            )
        )

    # Classification result (D38 alignment)
    classification_result = data.get("classification_result")
    if isinstance(classification_result, str):
        try:
            classification_result = json.loads(classification_result)
        except json.JSONDecodeError:
            classification_result = None
    # Validate classification has required shape for SDK schema
    if isinstance(classification_result, dict):
        required_keys = {"intent", "channel", "techniques", "actions", "persona", "risk_score", "taxonomy_version"}
        if not required_keys.issubset(classification_result.keys()):
            classification_result = None

    case_kwargs: dict[str, Any] = dict(
        id=data["case_id"],
        title=props.get("title", f"Case {data['case_id'][:8]}"),
        status=data["status"],
        priority=data["priority"],
        assignee=data["assigned_to"],
        updatedAt=data["last_updated"] or data["queued_at"],
        queue="General",
        tags=tags,
        progress=props.get("progress"),
        dueAt=props.get("dueAt"),
        description=data.get("text", "")[:1000] if data.get("text") else "No description available.",
        artifacts=artifacts,
        timeline=timeline_events,
        graph_nodes=nodes,
        graph_links=links,
    )
    if classification_result is not None:
        case_kwargs["classification"] = classification_result
    return CaseDetail(**case_kwargs)


# --- Helpers ---


_MIME_TYPE_MAP: dict[str, str] = {
    "application/pdf": "document",
    "application/json": "data",
    "text/markdown": "document",
    "text/plain": "document",
    "text/html": "document",
    "application/zip": "archive",
    "application/x-zip-compressed": "archive",
    "image/png": "screenshot",
    "image/jpeg": "screenshot",
    "image/webp": "screenshot",
}


def _mime_to_artifact_type(mime: str) -> str:
    """Map a MIME type to a human-friendly artifact type label.

    Args:
        mime: MIME type string.

    Returns:
        An artifact type like 'document', 'screenshot', 'data', etc.
    """
    return _MIME_TYPE_MAP.get(mime, "document")


# Human-friendly labels for SSI timeline event types
_TIMELINE_LABELS: dict[str, str] = {
    "investigation_submitted": "Investigation submitted",
    "classification_completed": "Classification completed",
    "wallets_harvested": "Wallet addresses harvested",
    "evidence_collected": "Evidence collected",
    "report_generated": "Report generated",
    "case_created": "Case created",
    "enqueued": "Case enqueued for review",
    "status_change": "Status changed",
    "comment": "Comment added",
    "assignment": "Case assigned",
}


def _format_timeline_description(action: str, payload: Any) -> str:
    """Build a human-readable timeline description from an action + payload.

    For SSI-generated events the payload dict contains a pre-formatted
    ``description`` key which is used directly.  Legacy review-action rows
    fall back to ``"{action}: {payload}"``.

    Args:
        action: The action/type key stored in ``review_actions.action``.
        payload: The JSON payload column (dict or string).

    Returns:
        A single-line description string.
    """
    # SSI events store a structured payload with a description key
    if isinstance(payload, dict) and "description" in payload:
        return payload["description"]

    # JSON-string payloads
    if isinstance(payload, str):
        try:
            parsed = json.loads(payload)
            if isinstance(parsed, dict) and "description" in parsed:
                return parsed["description"]
        except (json.JSONDecodeError, TypeError):
            pass

    label = _TIMELINE_LABELS.get(action, action)
    detail = ""
    if isinstance(payload, dict):
        detail = payload.get("detail", "")
    elif isinstance(payload, str) and payload:
        detail = payload
    if detail:
        return f"{label}: {detail}"
    return label


# --- Write endpoints (used by SSI CoreBridge) ---


def _get_or_404(session: Any, case_id: str) -> None:
    """Raise 404 if *case_id* does not exist in the cases table."""
    row = session.execute(
        sa.select(sql_schema.cases.c.case_id).where(sql_schema.cases.c.case_id == case_id)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")


@router.post("", summary="Create a new case", response_model=CreateCaseResponse, status_code=201)
def create_case(body: CreateCaseRequest) -> CreateCaseResponse:
    """Create a case record and enqueue it for review.

    Called by SSI's ``CoreBridge`` after an investigation completes.
    Inserts into the ``cases`` table and creates a ``review_queue`` entry
    so the analyst console can display the case immediately.

    Args:
        body: Case creation payload.

    Returns:
        The assigned ``case_id``.
    """
    case_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    # Build a content hash from metadata + source_url for dedup
    raw_content = json.dumps(body.metadata or {}, sort_keys=True) + (body.source_url or "")
    raw_text_sha256 = hashlib.sha256(raw_content.encode()).hexdigest()

    sf = build_sql_session_factory()
    with sf() as session:
        # Check for existing case with same dataset + hash (dedup)
        existing = session.execute(
            sa.select(sql_schema.cases.c.case_id)
            .where(sql_schema.cases.c.dataset == body.dataset)
            .where(sql_schema.cases.c.raw_text_sha256 == raw_text_sha256)
        ).scalar()

        if existing:
            # Update the existing case rather than duplicating
            update_vals: dict[str, Any] = {"updated_at": now}
            if body.classification_result:
                update_vals["classification_result"] = body.classification_result
                update_vals["classification_status"] = "completed"
            if body.risk_score is not None:
                update_vals["risk_score"] = body.risk_score
            if body.metadata:
                update_vals["metadata"] = body.metadata
            session.execute(
                sa.update(sql_schema.cases)
                .where(sql_schema.cases.c.case_id == existing)
                .values(**update_vals)
            )
            session.commit()
            return CreateCaseResponse(case_id=existing, created=False)

        # Build a display title: explicit > metadata > source_url domain > case_id
        title = body.title
        if not title:
            meta = body.metadata or {}
            title = meta.get("title")
        if not title and body.source_url:
            from urllib.parse import urlparse

            try:
                domain = urlparse(body.source_url).netloc or body.source_url
                if domain.startswith("www."):
                    domain = domain[4:]
                title = f"Investigation — {domain}"
            except Exception:
                title = f"Investigation — {body.source_url[:60]}"
        if not title:
            title = f"Case {case_id[:8]}"

        # Ensure title is in metadata so list/detail views can read it
        enriched_metadata = dict(body.metadata or {})
        enriched_metadata.setdefault("title", title)

        # Insert new case
        session.execute(
            sa.insert(sql_schema.cases).values(
                case_id=case_id,
                dataset=body.dataset,
                source_type=body.source_type,
                classification=None,
                classification_status="completed" if body.classification_result else "pending",
                classification_result=body.classification_result,
                confidence=0,
                risk_score=body.risk_score or 0,
                raw_text_sha256=raw_text_sha256,
                status="open",
                metadata=enriched_metadata,
                created_at=now,
                updated_at=now,
            )
        )

        # Insert a scam_records row so the dashboard join finds this case
        session.execute(
            dialect_insert(session, sql_schema.scam_records)
            .values(
                case_id=case_id,
                text=body.source_url or "",
                entities=None,
                classification=None,
                confidence=0,
                classification_result=body.classification_result,
                tags=None,
                created_at=now,
                metadata=enriched_metadata,
            )
            .on_conflict_do_nothing(index_elements=["case_id"])
        )
        session.commit()

    # Enqueue for analyst review
    store = build_review_store()
    priority = "high" if (body.risk_score or 0) >= 70 else "medium"
    store.enqueue_case(
        case_id=case_id,
        priority=priority,
        classification_result=body.classification_result,
    )

    logger.info("Created case %s (dataset=%s, risk=%.1f)", case_id, body.dataset, body.risk_score or 0)
    return CreateCaseResponse(case_id=case_id, created=True)


@router.patch("/{case_id}", summary="Update case fields")
def update_case(case_id: str, body: UpdateCaseRequest) -> dict[str, Any]:
    """Update mutable fields on an existing case.

    Typically called by SSI ``CoreBridge._store_classification`` to push
    the fraud taxonomy result after case creation.

    Args:
        case_id: The case to update.
        body: Fields to patch.

    Returns:
        Confirmation dict with the ``case_id``.
    """
    sf = build_sql_session_factory()
    now = datetime.now(timezone.utc)

    update_vals: dict[str, Any] = {"updated_at": now}
    if body.classification_result is not None:
        update_vals["classification_result"] = body.classification_result
    if body.classification_status is not None:
        update_vals["classification_status"] = body.classification_status
    if body.risk_score is not None:
        update_vals["risk_score"] = body.risk_score
    if body.status is not None:
        update_vals["status"] = body.status
    if body.tags is not None:
        update_vals["tags"] = body.tags
    if body.metadata is not None:
        update_vals["metadata"] = body.metadata

    with sf() as session:
        _get_or_404(session, case_id)
        session.execute(
            sa.update(sql_schema.cases)
            .where(sql_schema.cases.c.case_id == case_id)
            .values(**update_vals)
        )
        session.commit()

    return {"case_id": case_id, "updated": True}


@router.post(
    "/{case_id}/entities/batch",
    summary="Batch-create entities on a case",
    response_model=BatchEntitiesResponse,
    status_code=201,
)
def batch_create_entities(case_id: str, body: BatchEntitiesRequest) -> BatchEntitiesResponse:
    """Upsert a batch of entities linked to *case_id*.

    Each entity is identified by ``(case_id, entity_type, canonical_value)``.
    Existing matches are updated; new ones are inserted.

    Args:
        case_id: Parent case.
        body: List of entities.

    Returns:
        Count of entities written.
    """
    sf = build_sql_session_factory()
    now = datetime.now(timezone.utc)

    with sf() as session:
        _get_or_404(session, case_id)

        created = 0
        for entity in body.entities:
            entity_id = str(uuid.uuid4())
            # Try update first (natural key: case + type + canonical_value)
            result = session.execute(
                sa.update(sql_schema.entities)
                .where(sql_schema.entities.c.case_id == case_id)
                .where(sql_schema.entities.c.entity_type == entity.entity_type)
                .where(sql_schema.entities.c.canonical_value == entity.canonical_value)
                .values(
                    raw_value=entity.raw_value,
                    confidence=entity.confidence,
                    last_seen_at=now,
                    metadata=entity.metadata,
                    updated_at=now,
                )
            )
            if result.rowcount == 0:
                session.execute(
                    sa.insert(sql_schema.entities).values(
                        entity_id=entity_id,
                        case_id=case_id,
                        entity_type=entity.entity_type,
                        canonical_value=entity.canonical_value,
                        raw_value=entity.raw_value,
                        confidence=entity.confidence,
                        first_seen_at=now,
                        last_seen_at=now,
                        metadata=entity.metadata,
                        created_at=now,
                        updated_at=now,
                    )
                )
            created += 1
        session.commit()

    logger.info("Upserted %d entities on case %s", created, case_id)
    return BatchEntitiesResponse(case_id=case_id, created=created)


@router.post(
    "/{case_id}/indicators/batch",
    summary="Batch-create indicators on a case",
    response_model=BatchIndicatorsResponse,
    status_code=201,
)
def batch_create_indicators(case_id: str, body: BatchIndicatorsRequest) -> BatchIndicatorsResponse:
    """Upsert a batch of indicators linked to *case_id*.

    Each indicator is identified by ``(dataset, category, number)``
    matching the unique constraint on the ``indicators`` table.
    Existing matches are updated; new ones are inserted.

    Args:
        case_id: Parent case.
        body: List of indicators.

    Returns:
        Count of indicators written.
    """
    sf = build_sql_session_factory()
    now = datetime.now(timezone.utc)

    with sf() as session:
        _get_or_404(session, case_id)

        created = 0
        for ind in body.indicators:
            indicator_id = str(uuid.uuid4())
            dataset = ind.dataset or "ssi"

            # Try update by natural key (dataset + category + number)
            result = session.execute(
                sa.update(sql_schema.indicators)
                .where(sql_schema.indicators.c.dataset == dataset)
                .where(sql_schema.indicators.c.category == ind.category)
                .where(sql_schema.indicators.c.number == ind.number)
                .values(
                    case_id=case_id,
                    type=ind.type,
                    item=ind.item,
                    status=ind.status,
                    confidence=ind.confidence,
                    last_seen_at=now,
                    metadata=ind.metadata,
                    updated_at=now,
                )
            )
            if result.rowcount == 0:
                session.execute(
                    sa.insert(sql_schema.indicators).values(
                        indicator_id=indicator_id,
                        case_id=case_id,
                        category=ind.category,
                        item=ind.item,
                        type=ind.type,
                        number=ind.number,
                        status=ind.status,
                        confidence=ind.confidence,
                        first_seen_at=now,
                        last_seen_at=now,
                        dataset=dataset,
                        metadata=ind.metadata,
                        created_at=now,
                        updated_at=now,
                    )
                )
            created += 1
        session.commit()

    logger.info("Upserted %d indicators on case %s", created, case_id)
    return BatchIndicatorsResponse(case_id=case_id, created=created)


# --- Timeline Endpoints ---


@router.post(
    "/{case_id}/timeline",
    summary="Add timeline events to a case",
    response_model=BatchTimelineResponse,
    status_code=201,
)
def add_timeline_events(case_id: str, body: BatchTimelineRequest) -> BatchTimelineResponse:
    """Append one or more timeline events to a case's audit trail.

    Each event is inserted as a ``review_actions`` row so it appears in
    the case detail timeline.  Typically called by SSI's ``CoreBridge``
    to record investigation milestones (scan started, classification
    completed, wallets found, report generated, etc.).

    Args:
        case_id: The parent case.
        body: Batch of timeline events.

    Returns:
        Count of events created.
    """
    store = build_review_store()

    # Look up review_id for this case
    sf = build_sql_session_factory()
    with sf() as session:
        _get_or_404(session, case_id)
        review_id = session.execute(
            sa.select(sql_schema.review_queue.c.review_id).where(
                sql_schema.review_queue.c.case_id == case_id
            )
        ).scalar()

    if not review_id:
        raise HTTPException(status_code=404, detail="Case has no review queue entry")

    created = 0
    for event in body.events:
        ts = event.timestamp or datetime.now(timezone.utc)
        store.log_action(
            review_id=review_id,
            action=event.type,
            actor=event.actor,
            payload={"description": event.description, "timestamp": ts.isoformat()},
        )
        created += 1

    logger.info("Added %d timeline events to case %s", created, case_id)
    return BatchTimelineResponse(case_id=case_id, created=created)


# --- GDPR Compliance Endpoints ---


@router.get(
    "/{case_id}/export",
    summary="GDPR data export",
    response_class=JSONResponse,
    dependencies=[Depends(require_role("admin"))],
)
def export_case(case_id: str) -> JSONResponse:
    """Return all data associated with a case as JSON (GDPR Article 20).

    Requires ``admin`` role.
    """
    service = build_retention_service()
    try:
        payload = service.export_case_data(case_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Case not found")
    return JSONResponse(content=payload)


@router.delete(
    "/{case_id}",
    summary="GDPR deletion",
    dependencies=[Depends(require_role("admin"))],
)
def delete_case(case_id: str) -> dict[str, Any]:
    """Hard-delete a case and all associated data (GDPR Article 17).

    Cascades to PII vault tokens, evidence files, and vector embeddings.
    Requires ``admin`` role.
    """
    service = build_retention_service()
    try:
        result = service.gdpr_delete_case(case_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Case not found")
    return result
