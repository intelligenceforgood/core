"""Case summaries that hydrate the console while analytics services remain stubbed."""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Literal
from pydantic import Field

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from i4g.api.auth import require_role, require_token
from i4g.api.camel import CamelModel
from i4g.api.response_models import CasesListResponse
from i4g.services.factories import build_retention_service, build_review_store

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
    id: str
    label: str
    type: str
    data: dict[str, Any] = Field(default_factory=dict)


class CaseGraphLink(CamelModel):
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
        timeline_events.append(
            CaseTimelineEvent(
                id=action["action_id"],
                timestamp=ts,
                description=f"{action['action']}: {action.get('payload') or ''}",
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

    # Artifacts (Files)
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
        title=props.get("title", f"Investigation {data['case_id']}"),
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
