"""Static taxonomy data."""

from typing import Any, Dict, List

TAXONOMY_TREE_RESPONSE: Dict[str, Any] = {
    "steward": "Policy & Standards Team",
    "updatedAt": "2025-11-18T09:30:00Z",
    "nodes": [
        {
            "id": "tax-trafficking",
            "label": "Trafficking",
            "description": "Indicators and cases relating to human trafficking.",
            "count": 128,
            "children": [
                {
                    "id": "tax-trafficking-labor",
                    "label": "Labor Exploitation",
                    "description": "Forced or coerced labor scenarios.",
                    "count": 54,
                    "children": [],
                },
                {
                    "id": "tax-trafficking-sex",
                    "label": "Sexual Exploitation",
                    "description": "Sexual exploitation and related offenses.",
                    "count": 47,
                    "children": [],
                },
            ],
        },
        {
            "id": "tax-financial",
            "label": "Financial Facilitation",
            "description": "Money movement supporting suspicious activity.",
            "count": 86,
            "children": [
                {
                    "id": "tax-financial-shell",
                    "label": "Shell Companies",
                    "description": "Use of shell entities to mask flows.",
                    "count": 31,
                    "children": [],
                },
                {
                    "id": "tax-financial-remittance",
                    "label": "Remittance Patterns",
                    "description": "Structured remittances suggesting laundering.",
                    "count": 19,
                    "children": [],
                },
            ],
        },
        {
            "id": "tax-intake",
            "label": "Partner Intake",
            "description": "Signals sourced from NGO and hotline partners.",
            "count": 63,
            "children": [
                {
                    "id": "tax-intake-hotline",
                    "label": "Hotline",
                    "description": "Hotline submissions and escalations.",
                    "count": 28,
                    "children": [],
                },
                {
                    "id": "tax-intake-shelter",
                    "label": "Shelter",
                    "description": "Reports from shelter partners.",
                    "count": 17,
                    "children": [],
                },
            ],
        },
    ],
}
