"""Tests for role-based access control on intelligence endpoints.

Covers researcher restrictions (anonymized list, 403 on detail) and
analyst/LEO/admin full-access scenarios.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from i4g.api.app import create_app
from i4g.api.auth import require_token
from i4g.api.intelligence import get_analytics_store, get_campaign_store

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

_ENTITY = {
    "entity_type": "crypto_wallet",
    "canonical_value": "0xABCDEF1234567890",
    "case_count": 5,
    "loss_sum": 150000.0,
    "status": "active",
    "case_ids": ["c1"],
    "campaign_ids": [],
}

_INDICATOR = {
    "indicator_id": "ind-001",
    "indicator_value": "192.168.1.100",
    "category": "ip",
    "case_count": 3,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(role: str) -> dict[str, str]:
    """Create a fake user dict for a given role."""
    return {"username": f"test-{role}@i4g.dev", "role": role}


def _build_client(role: str, mock_store: MagicMock, mock_camp: MagicMock) -> TestClient:
    """Return a TestClient where require_token yields the given role."""
    app = create_app()
    app.dependency_overrides[require_token] = lambda: _make_user(role)
    app.dependency_overrides[get_analytics_store] = lambda: mock_store
    app.dependency_overrides[get_campaign_store] = lambda: mock_camp
    return TestClient(app)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_store() -> MagicMock:
    """Mock AnalyticsStore."""
    s = MagicMock()
    s.list_entity_stats.return_value = [dict(_ENTITY)]
    s.get_entity_stat.return_value = dict(_ENTITY)
    s.list_indicator_stats.return_value = [dict(_INDICATOR)]
    s.get_indicator_stat.return_value = dict(_INDICATOR)
    s.get_entity_activity.return_value = []
    s.get_entity_neighbors.return_value = []
    s.get_latest_kpi.return_value = {"new_indicators": 0}
    s.list_platform_kpis.return_value = []
    return s


@pytest.fixture()
def mock_camp() -> MagicMock:
    """Mock ThreatCampaignStore."""
    c = MagicMock()
    c.list_campaigns.return_value = []
    c.get_campaign.return_value = None
    return c


# ---------------------------------------------------------------------------
# Researcher restrictions
# ---------------------------------------------------------------------------


class TestResearcherRole:
    """Researcher gets anonymized lists and 403 on detail endpoints."""

    def test_entity_list_anonymized(self, mock_store: MagicMock, mock_camp: MagicMock) -> None:
        """Researcher sees masked canonical_value in entity list."""
        client = _build_client("researcher", mock_store, mock_camp)
        resp = client.get("/intelligence/entities")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        val = items[0]["canonical_value"]
        # Long value → last 4 chars shown with ***
        assert val.startswith("***")
        assert val.endswith("7890")

    def test_entity_detail_forbidden(self, mock_store: MagicMock, mock_camp: MagicMock) -> None:
        """Researcher cannot access individual entity detail."""
        client = _build_client("researcher", mock_store, mock_camp)
        resp = client.get("/intelligence/entities/crypto_wallet/0xABCDEF1234567890")
        assert resp.status_code == 403

    def test_indicator_list_anonymized(self, mock_store: MagicMock, mock_camp: MagicMock) -> None:
        """Researcher sees masked indicator_value in indicator list."""
        client = _build_client("researcher", mock_store, mock_camp)
        resp = client.get("/intelligence/indicators")
        assert resp.status_code == 200
        items = resp.json()["items"]
        val = items[0]["indicator_value"]
        assert val.startswith("***")

    def test_indicator_detail_forbidden(self, mock_store: MagicMock, mock_camp: MagicMock) -> None:
        """Researcher cannot access individual indicator detail."""
        client = _build_client("researcher", mock_store, mock_camp)
        resp = client.get("/intelligence/indicators/ind-001")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Analyst full access
# ---------------------------------------------------------------------------


class TestAnalystRole:
    """Analyst gets full unmasked access."""

    def test_entity_list_unmasked(self, mock_store: MagicMock, mock_camp: MagicMock) -> None:
        """Analyst sees full canonical_value."""
        client = _build_client("analyst", mock_store, mock_camp)
        resp = client.get("/intelligence/entities")
        items = resp.json()["items"]
        assert items[0]["canonical_value"] == "0xABCDEF1234567890"

    def test_entity_detail_allowed(self, mock_store: MagicMock, mock_camp: MagicMock) -> None:
        """Analyst can access entity detail."""
        client = _build_client("analyst", mock_store, mock_camp)
        resp = client.get("/intelligence/entities/crypto_wallet/0xABCDEF1234567890")
        assert resp.status_code == 200

    def test_indicator_detail_allowed(self, mock_store: MagicMock, mock_camp: MagicMock) -> None:
        """Analyst can access indicator detail."""
        client = _build_client("analyst", mock_store, mock_camp)
        resp = client.get("/intelligence/indicators/ind-001")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# LEO and Admin full access
# ---------------------------------------------------------------------------


class TestLeoAndAdminRoles:
    """LEO and Admin have full access like analyst."""

    @pytest.mark.parametrize("role", ["leo", "admin"])
    def test_entity_detail_allowed(self, role: str, mock_store: MagicMock, mock_camp: MagicMock) -> None:
        """LEO/Admin can access entity detail."""
        client = _build_client(role, mock_store, mock_camp)
        resp = client.get("/intelligence/entities/crypto_wallet/0xABCDEF1234567890")
        assert resp.status_code == 200

    @pytest.mark.parametrize("role", ["leo", "admin"])
    def test_indicator_detail_allowed(self, role: str, mock_store: MagicMock, mock_camp: MagicMock) -> None:
        """LEO/Admin can access indicator detail."""
        client = _build_client(role, mock_store, mock_camp)
        resp = client.get("/intelligence/indicators/ind-001")
        assert resp.status_code == 200

    @pytest.mark.parametrize("role", ["leo", "admin"])
    def test_entity_list_unmasked(self, role: str, mock_store: MagicMock, mock_camp: MagicMock) -> None:
        """LEO/Admin sees full values."""
        client = _build_client(role, mock_store, mock_camp)
        resp = client.get("/intelligence/entities")
        items = resp.json()["items"]
        assert items[0]["canonical_value"] == "0xABCDEF1234567890"


# ---------------------------------------------------------------------------
# User role — full list access, full detail access
# ---------------------------------------------------------------------------


class TestUserRole:
    """Regular user gets full access (above researcher)."""

    def test_entity_detail_allowed(self, mock_store: MagicMock, mock_camp: MagicMock) -> None:
        """Regular user can access entity detail."""
        client = _build_client("user", mock_store, mock_camp)
        resp = client.get("/intelligence/entities/crypto_wallet/0xABCDEF1234567890")
        assert resp.status_code == 200

    def test_entity_list_unmasked(self, mock_store: MagicMock, mock_camp: MagicMock) -> None:
        """Regular user sees full values."""
        client = _build_client("user", mock_store, mock_camp)
        resp = client.get("/intelligence/entities")
        items = resp.json()["items"]
        assert items[0]["canonical_value"] == "0xABCDEF1234567890"
