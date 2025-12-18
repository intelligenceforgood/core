"""Case summaries that hydrate the console while analytics services remain stubbed."""

from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/cases", tags=["cases"])

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
            "title": "Group-7 cross-border trafficking investigation",
            "priority": "critical",
            "status": "active",
            "updatedAt": "2025-11-19T08:41:00Z",
            "assignee": "J. Alvarez",
            "queue": "Rapid Response",
            "tags": ["trafficking", "group-7", "cross-border"],
            "progress": 68,
            "dueAt": "2025-11-21T17:00:00Z",
        },
        {
            "id": "case-417",
            "title": "Warehouse labor exploitation probe",
            "priority": "high",
            "status": "awaiting-input",
            "updatedAt": "2025-11-18T15:20:00Z",
            "assignee": "A. Chen",
            "queue": "Policy Review",
            "tags": ["labor", "warehouse", "child-labor"],
            "progress": 42,
            "dueAt": "2025-11-22T12:00:00Z",
        },
        {
            "id": "case-399",
            "title": "Financial facilitation cluster",
            "priority": "medium",
            "status": "active",
            "updatedAt": "2025-11-18T11:05:00Z",
            "assignee": "M. Singh",
            "queue": "Financial Intelligence",
            "tags": ["finance", "shell", "group-7"],
            "progress": 54,
            "dueAt": None,
        },
        {
            "id": "case-364",
            "title": "Partner intake review backlog",
            "priority": "low",
            "status": "blocked",
            "updatedAt": "2025-11-16T09:37:00Z",
            "assignee": "D. Rivera",
            "queue": "NGO Coordination",
            "tags": ["intake", "partner"],
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
