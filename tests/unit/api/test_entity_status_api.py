"""Tests for the entity status management API (Sprint 4 — S4-14).

Covers POST /intelligence/entities/status with status transitions.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from i4g.api.app import create_app
from i4g.api.intelligence import get_analytics_store, get_annotation_store, get_campaign_store

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_analytics_store() -> MagicMock:
    """Create a mock AnalyticsStore with update_entity_status support."""
    store = MagicMock()
    store.update_entity_status.return_value = True
    return store


@pytest.fixture()
def mock_campaign_store() -> MagicMock:
    """Create a noop ThreatCampaignStore mock."""
    return MagicMock()


@pytest.fixture()
def mock_annotation_store() -> MagicMock:
    """Create a noop AnnotationStore mock."""
    return MagicMock()


@pytest.fixture()
def client(mock_analytics_store, mock_campaign_store, mock_annotation_store) -> TestClient:
    """Create a TestClient with mocked stores."""
    app = create_app()
    app.dependency_overrides[get_analytics_store] = lambda: mock_analytics_store
    app.dependency_overrides[get_campaign_store] = lambda: mock_campaign_store
    app.dependency_overrides[get_annotation_store] = lambda: mock_annotation_store
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Status update — valid transitions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["active", "dormant", "flagged", "taken_down"])
def test_update_entity_status_valid(client: TestClient, status: str) -> None:
    """POST /intelligence/entities/status accepts all valid statuses."""
    resp = client.post(
        "/intelligence/entities/status",
        json={"entityType": "wallet", "canonicalValue": "0xAAA", "status": status},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == status
    assert body["entity_type"] == "wallet"
    assert body["canonical_value"] == "0xAAA"


def test_update_entity_status_calls_store(client: TestClient, mock_analytics_store: MagicMock) -> None:
    """Status update forwards to analytics_store.update_entity_status."""
    client.post(
        "/intelligence/entities/status",
        json={"entityType": "email", "canonicalValue": "a@b.com", "status": "flagged"},
    )
    mock_analytics_store.update_entity_status.assert_called_once_with(
        entity_type="email",
        canonical_value="a@b.com",
        status="flagged",
    )


# ---------------------------------------------------------------------------
# Status update — error cases
# ---------------------------------------------------------------------------


def test_update_entity_status_invalid_status(client: TestClient) -> None:
    """Invalid status returns 400."""
    resp = client.post(
        "/intelligence/entities/status",
        json={"entityType": "wallet", "canonicalValue": "0xAAA", "status": "retired"},
    )
    assert resp.status_code == 400


def test_update_entity_status_not_found(client: TestClient, mock_analytics_store: MagicMock) -> None:
    """Entity not found returns 404."""
    mock_analytics_store.update_entity_status.return_value = False
    resp = client.post(
        "/intelligence/entities/status",
        json={"entityType": "wallet", "canonicalValue": "nonexistent", "status": "active"},
    )
    assert resp.status_code == 404
