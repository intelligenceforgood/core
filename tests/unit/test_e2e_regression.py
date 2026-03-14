"""E2E regression smoke tests for TIFAP user journeys (S6-24).

These tests verify that all major API endpoints return valid responses
when hit in sequence, simulating the four user journeys from PRD Section 9.

Requires a bootstrapped local environment:
    i4g bootstrap local reset --report-dir data/reports/bootstrap_local
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


def _mock_auth():
    """Patch auth to bypass token validation."""
    return patch(
        "i4g.api.auth.require_token",
        return_value={"sub": "test@test.com", "role": "admin"},
    )


@pytest.fixture()
def client():
    """Test client with mocked auth."""
    with _mock_auth():
        from fastapi.testclient import TestClient

        from i4g.api.app import create_app

        app = create_app()
        return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Journey A: Analyst workstream — search → review → report
# ---------------------------------------------------------------------------


def test_journey_a_dashboard(client) -> None:
    """Journey A: Dashboard overview loads."""
    resp = client.get("/dashboard/overview")
    assert resp.status_code in (200, 404)  # 404 acceptable if no data yet


def test_journey_a_intelligence_entities(client) -> None:
    """Journey A: Entity explorer listing."""
    resp = client.get("/intelligence/entities")
    assert resp.status_code == 200


def test_journey_a_intelligence_indicators(client) -> None:
    """Journey A: Indicator registry listing."""
    resp = client.get("/intelligence/indicators")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Journey B: Campaign intelligence
# ---------------------------------------------------------------------------


def test_journey_b_campaign_list(client) -> None:
    """Journey B: Campaign listing."""
    resp = client.get("/intelligence/campaigns")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Journey C: Impact and reporting
# ---------------------------------------------------------------------------


def test_journey_c_impact_dashboard(client) -> None:
    """Journey C: Impact dashboard KPIs."""
    resp = client.get("/impact/dashboard")
    assert resp.status_code == 200


def test_journey_c_impact_loss(client) -> None:
    """Journey C: Loss by taxonomy."""
    resp = client.get("/impact/loss-by-taxonomy")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Journey D: Partner / external
# ---------------------------------------------------------------------------


def test_journey_d_feeds_require_partner_key(client) -> None:
    """Journey D: Partner feed rejects unauthenticated access."""
    resp = client.get("/feeds/indicators")
    assert resp.status_code in (401, 403, 422)
