"""Expose lightweight analytics payloads for the console overview page."""

from fastapi import APIRouter

router = APIRouter(prefix="/analytics", tags=["analytics"])

_ANALYTICS_OVERVIEW = {
    "metrics": [
        {
            "id": "metric-detection-rate",
            "label": "Detection rate",
            "value": "87%",
            "change": "+3.2 pts vs last month",
            "trend": "up",
        },
        {
            "id": "metric-time-to-action",
            "label": "Median time to action",
            "value": "9.4h",
            "change": "-1.1h vs last week",
            "trend": "down",
        },
        {
            "id": "metric-proactive",
            "label": "Proactive interventions",
            "value": "42",
            "change": "+6 vs last week",
            "trend": "up",
        },
        {
            "id": "metric-sla",
            "label": "SLA adherence",
            "value": "94%",
            "change": "-2 pts vs target",
            "trend": "down",
        },
    ],
    "detectionRateSeries": [
        {"label": "Mon", "value": 79},
        {"label": "Tue", "value": 82},
        {"label": "Wed", "value": 85},
        {"label": "Thu", "value": 88},
        {"label": "Fri", "value": 87},
    ],
    "pipelineBreakdown": [
        {"label": "Intake", "value": 34},
        {"label": "Data fusion", "value": 26},
        {"label": "Human review", "value": 19},
        {"label": "Policy", "value": 12},
        {"label": "Action", "value": 9},
    ],
    "geographyBreakdown": [
        {"region": "North America", "value": 28},
        {"region": "Europe", "value": 22},
        {"region": "LATAM", "value": 18},
        {"region": "Asia-Pacific", "value": 25},
        {"region": "Africa", "value": 9},
    ],
    "weeklyIncidents": [
        {"week": "W32", "incidents": 18, "interventions": 12},
        {"week": "W33", "incidents": 21, "interventions": 15},
        {"week": "W34", "incidents": 25, "interventions": 19},
        {"week": "W35", "incidents": 24, "interventions": 18},
        {"week": "W36", "incidents": 27, "interventions": 20},
    ],
}


@router.get("/overview", summary="Return canned analytics trends")
def get_analytics_overview() -> dict[str, object]:
    """Return the analytics payload used by the console analytics charts."""

    return _ANALYTICS_OVERVIEW
