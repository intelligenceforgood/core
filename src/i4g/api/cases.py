"""Case summaries that hydrate the console while analytics services remain stubbed."""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from pydantic import Field

from fastapi import APIRouter, Depends, HTTPException

from i4g.api.auth import require_token
from i4g.api.camel import CamelModel
from i4g.services.factories import build_review_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cases", tags=["cases"], dependencies=[Depends(require_token)])

# --- Schemas ---


class CaseArtifact(CamelModel):
    id: str
    type: str = Field(..., description="Type of artifact (document, image, etc.)")
    name: str = Field(..., description="Display name of the artifact")
    url: Optional[str] = Field(None, description="Link to the artifact content")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CaseTimelineEvent(CamelModel):
    id: str
    timestamp: datetime
    description: str
    actor: Optional[str] = Field(None, description="User or system actor")
    type: str = Field(..., description="Type of event (comment, status_change, alert)")


class CaseGraphNode(CamelModel):
    id: str
    label: str
    type: str
    data: Dict[str, Any] = Field(default_factory=dict)


class CaseGraphLink(CamelModel):
    source: str
    target: str
    relation: str


# Enum-like types matching SDK Zod schemas
CaseStatus = Literal["new", "in_review", "awaiting_input", "closed", "accepted", "rejected"]
CasePriority = Literal["critical", "high", "medium", "low"]


class CaseDetail(CamelModel):
    """Detailed view of a case for the investigation workspace."""

    id: str
    title: str
    status: CaseStatus
    priority: CasePriority
    assignee: Optional[str] = None
    updated_at: Optional[str] = None
    queue: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    progress: Optional[int] = None
    due_at: Optional[str] = None
    classification: Optional[Dict[str, Any]] = Field(
        None,
        description="Fraud classification result (intent, channel, techniques, actions, persona, risk_score, etc.)",
    )
    description: str = Field("", description="Detailed narrative of the case")
    artifacts: List[CaseArtifact] = Field(default_factory=list)
    timeline: List[CaseTimelineEvent] = Field(default_factory=list)
    graph_nodes: List[CaseGraphNode] = Field(default_factory=list)
    graph_links: List[CaseGraphLink] = Field(default_factory=list)


# --- Data ---

CASES_RESPONSE: dict[str, Any] = {
    "summary": {
        "active": 18,
        "dueToday": 4,
        "pendingReview": 7,
        "escalations": 3,
    },
    "cases": [
        {
            "id": "case-482",
            "title": "Suspected Imposter Network",
            "priority": "critical",
            "status": "in_review",
            "updatedAt": "2026-01-09T08:41:00Z",
            "assignee": "J. Alvarez",
            "queue": "Rapid Response",
            "tags": ["INTENT.IMPOSTER", "CHANNEL.SMS", "SE.URGENCY"],
            "progress": 68,
            "dueAt": "2026-01-11T17:00:00Z",
        },
        {
            "id": "case-417",
            "title": "Crypto Investment Scheme",
            "priority": "high",
            "status": "new",
            "updatedAt": "2026-01-08T15:20:00Z",
            "assignee": "A. Chen",
            "queue": "Policy Review",
            "tags": ["INTENT.INVESTMENT", "ACTION.CRYPTO", "SE.SCARCITY"],
            "progress": 42,
            "dueAt": "2026-01-12T12:00:00Z",
        },
        {
            "id": "case-399",
            "title": "Romance Scam Escalation",
            "priority": "medium",
            "status": "in_review",
            "updatedAt": "2026-01-08T11:05:00Z",
            "assignee": "M. Singh",
            "queue": "Financial Intelligence",
            "tags": ["INTENT.ROMANCE", "PERSONA.ROMANTIC", "SE.TRUST_BUILDING"],
            "progress": 54,
            "dueAt": None,
        },
        {
            "id": "case-364",
            "title": "Partner intake review backlog",
            "priority": "low",
            "status": "awaiting_input",
            "updatedAt": "2026-01-06T09:37:00Z",
            "assignee": "D. Rivera",
            "queue": "NGO Coordination",
            "tags": ["INTENT.CHARITY", "CHANNEL.SOCIAL"],
            "progress": 17,
            "dueAt": None,
        },
    ],
    "queues": [
        {
            "id": "queue-rapid-response",
            "name": "Rapid Response",
            "description": "Emergent escalations requiring 24h turnaround",
            "count": 5,
        },
        {
            "id": "queue-policy",
            "name": "Policy Review",
            "description": "Cases pending adjudication by policy team",
            "count": 7,
        },
        {
            "id": "queue-finance",
            "name": "Financial Intelligence",
            "description": "Cross-border payment analysis and tracing",
            "count": 4,
        },
        {
            "id": "queue-ngo",
            "name": "NGO Coordination",
            "description": "Partner intake triage and follow-up",
            "count": 6,
        },
    ],
}


@router.get("", summary="List active cases")
def list_cases(
    limit: int = 50,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    queue: Optional[str] = None,
    due_date: Optional[str] = None,
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
        # Fallback to canned response if not in DB (during migration phase)
        # This preserves behavior for existing "cases" in the mock list if they haven't been seeded yet.
        case_basics = next((c for c in CASES_RESPONSE["cases"] if c["id"] == case_id), None)
        if case_basics:
            return _build_mock_case(case_basics)

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


def _build_mock_case(case_basics: Dict[str, Any]) -> CaseDetail:
    """Helper to reconstruct the mock response for legacy/unseeded cases."""
    return CaseDetail(
        id=case_basics["id"],
        title=case_basics["title"],
        status=case_basics["status"],
        priority=case_basics["priority"],
        assignee=case_basics.get("assignee"),
        updatedAt=case_basics.get("updatedAt"),
        queue=case_basics.get("queue"),
        tags=case_basics.get("tags", []),
        progress=case_basics.get("progress"),
        dueAt=case_basics.get("dueAt"),
        description="[Backend Served - Mock Fallback] This case was not found in the DB, so we are serving the static mock.",
        artifacts=[
            CaseArtifact(
                id="art-1",
                type="document",
                name="Suspicious Transaction Report",
                url="/api/artifacts/docs/1",
                metadata={"file_size": "1.2MB"},
            ),
        ],
        timeline=[
            CaseTimelineEvent(
                id="evt-1",
                timestamp=datetime.now(timezone.utc),
                description="Case created automatically (Mock)",
                type="system",
            ),
        ],
        graph_nodes=[
            CaseGraphNode(id="n1", label="Subject A", type="person"),
            CaseGraphNode(id="n2", label="Account 123", type="account"),
        ],
        graph_links=[
            CaseGraphLink(source="n1", target="n2", relation="owns"),
        ],
    )
