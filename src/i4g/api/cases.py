"""Case summaries that hydrate the console while analytics services remain stubbed."""

from typing import Any, List, Optional, Dict
from datetime import datetime
from pydantic import BaseModel, Field

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/cases", tags=["cases"])

# --- Schemas ---


class CaseArtifact(BaseModel):
    id: str
    type: str = Field(..., description="Type of artifact (document, image, etc.)")
    name: str = Field(..., description="Display name of the artifact")
    url: Optional[str] = Field(None, description="Link to the artifact content")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CaseTimelineEvent(BaseModel):
    id: str
    timestamp: datetime
    description: str
    actor: Optional[str] = Field(None, description="User or system actor")
    type: str = Field(..., description="Type of event (comment, status_change, alert)")


class CaseGraphNode(BaseModel):
    id: str
    label: str
    type: str
    data: Dict[str, Any] = Field(default_factory=dict)


class CaseGraphLink(BaseModel):
    source: str
    target: str
    relation: str


class CaseDetail(BaseModel):
    """Detailed view of a case for the investigation workspace."""

    id: str
    title: str
    status: str
    priority: str
    assignee: Optional[str] = None
    updatedAt: Optional[str] = (
        None  # Keeping string to match existing dict style for simplicity, or should ideally parse
    )
    queue: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    progress: Optional[int] = None
    dueAt: Optional[str] = None
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
            "status": "active",
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
            "status": "awaiting-input",
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
            "status": "active",
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
            "status": "blocked",
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
def list_cases() -> dict[str, Any]:
    """Return canned summaries for the Cases console view."""

    return CASES_RESPONSE


@router.get("/{case_id}", response_model=CaseDetail, summary="Get case details")
async def get_case(case_id: str) -> CaseDetail:
    """Get full details for a specific case (Mocked)."""
    # 1. Try to find basic info in the static list
    case_basics = next((c for c in CASES_RESPONSE["cases"] if c["id"] == case_id), None)

    if not case_basics:
        # Fallback for ANY case- id to support testing
        if case_id.startswith("case-"):
            case_basics = {
                "id": case_id,
                "title": f"Investigation for {case_id}",
                "priority": "medium",
                "status": "active",
                "assignee": "analyst@example.com",
                "updatedAt": datetime.utcnow().isoformat(),
            }
        else:
            raise HTTPException(status_code=404, detail="Case not found")

    # 2. Enrich with detailed mock data
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
        description="[Backend Served] This is a detailed view of the investigation case. It includes artifacts, a timeline of events, and a relationship graph.",
        artifacts=[
            CaseArtifact(
                id="art-1",
                type="document",
                name="Suspicious Transaction Report",
                url="/api/artifacts/docs/1",
                metadata={"file_size": "1.2MB"},
            ),
            CaseArtifact(
                id="art-2",
                type="image",
                name="Check Screenshot",
                url="/api/artifacts/images/2",
                metadata={"dimensions": "1024x768"},
            ),
        ],
        timeline=[
            CaseTimelineEvent(
                id="evt-1",
                timestamp=datetime.utcnow(),
                description="Case created automatically by alert system",
                type="system",
            ),
            CaseTimelineEvent(
                id="evt-2",
                timestamp=datetime.utcnow(),
                description="Analyst started review",
                actor="analyst@example.com",
                type="status_change",
            ),
        ],
        graph_nodes=[
            CaseGraphNode(id="n1", label="Subject A", type="person"),
            CaseGraphNode(id="n2", label="Account 123", type="account"),
            CaseGraphNode(id="n3", label="Transaction 999", type="transaction"),
        ],
        graph_links=[
            CaseGraphLink(source="n1", target="n2", relation="owns"),
            CaseGraphLink(source="n2", target="n3", relation="originates"),
        ],
    )
