"""Sample case data for local bootstrap and development fixtures.

This data was previously inlined in ``i4g.api.cases`` (E26). It is now
extracted so the API module contains zero hardcoded mock data.  Only
import this module from bootstrap/seed tooling and test fixtures.
"""

from __future__ import annotations

from typing import Any

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
