"""Dashboard overview endpoints for analyst console."""

from fastapi import APIRouter

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/overview")
def get_dashboard_overview():
    """Return lightweight dashboard metrics used by the UI summary panel."""
    # These values are intentionally static for now; they keep the UI hydrated
    # during local runs where analytics backends are unavailable. When real
    # telemetry is ready, replace this with data pulled from the review/search
    # stores or a metrics service.
    return {
        "metrics": [
            {"label": "Active investigations", "value": "24", "change": "+12% vs last week"},
            {"label": "New leads this week", "value": "68", "change": "+5 sourced automatically"},
            {"label": "Cases at risk", "value": "6", "change": "Need follow-up within 24h"},
        ],
        "alerts": [
            {
                "id": "alert-1",
                "title": "Potential romance scam cluster",
                "detail": "10 new filings share overlapping bank accounts",
                "time": "15m ago",
                "variant": "warning",
            },
            {
                "id": "alert-2",
                "title": "Crypto mule pattern",
                "detail": "3 wallets reused across intake + customs",
                "time": "1h ago",
                "variant": "danger",
            },
        ],
        "activity": [
            {
                "id": "act-1",
                "title": "Analyst triaged case-102",
                "actor": "analyst_1",
                "when": "10m ago",
            },
            {
                "id": "act-2",
                "title": "Saved search updated",
                "actor": "analyst_2",
                "when": "25m ago",
            },
        ],
        "reminders": [
            {
                "id": "rem-1",
                "text": "Review weekly refresh metrics",
                "category": "data",
            },
            {
                "id": "rem-2",
                "text": "Coordinate with intake team on backlog",
                "category": "coordination",
            },
        ],
    }
