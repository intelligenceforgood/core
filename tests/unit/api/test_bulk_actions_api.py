"""Tests for the bulk entity actions API (Sprint 4 — S4-16/17).

Covers POST /intelligence/entities/bulk with export, tag, and status_update actions.
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
    """Create a mock AnalyticsStore with entity update support."""
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
# Export action
# ---------------------------------------------------------------------------


def test_bulk_export(client: TestClient) -> None:
    """Bulk export counts all entities as processed."""
    resp = client.post(
        "/intelligence/entities/bulk",
        json={
            "entityIds": ["wallet:0xAAA", "email:a@b.com"],
            "action": "export",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["processed"] == 2
    assert body["failed"] == 0


# ---------------------------------------------------------------------------
# Tag action
# ---------------------------------------------------------------------------


def test_bulk_tag(client: TestClient) -> None:
    """Bulk tag counts all entities as processed."""
    resp = client.post(
        "/intelligence/entities/bulk",
        json={
            "entityIds": ["wallet:0xAAA"],
            "action": "tag",
            "tag": "high-priority",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["processed"] == 1


# ---------------------------------------------------------------------------
# Status update action
# ---------------------------------------------------------------------------


def test_bulk_status_update(client: TestClient, mock_analytics_store: MagicMock) -> None:
    """Bulk status_update calls store for each entity."""
    resp = client.post(
        "/intelligence/entities/bulk",
        json={
            "entityIds": ["wallet:0xAAA", "email:a@b.com"],
            "action": "status_update",
            "status": "flagged",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["processed"] == 2
    assert body["failed"] == 0
    assert mock_analytics_store.update_entity_status.call_count == 2


def test_bulk_status_update_partial_failure(client: TestClient, mock_analytics_store: MagicMock) -> None:
    """Bulk status_update reports failures for missing entities."""
    mock_analytics_store.update_entity_status.side_effect = [True, False]

    resp = client.post(
        "/intelligence/entities/bulk",
        json={
            "entityIds": ["wallet:0xAAA", "wallet:missing"],
            "action": "status_update",
            "status": "dormant",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["processed"] == 1
    assert body["failed"] == 1
    assert len(body["errors"]) == 1


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


def test_bulk_invalid_action(client: TestClient) -> None:
    """Invalid action returns 400."""
    resp = client.post(
        "/intelligence/entities/bulk",
        json={
            "entityIds": ["wallet:0xAAA"],
            "action": "delete",
        },
    )
    assert resp.status_code == 400


def test_bulk_invalid_entity_id_format(client: TestClient) -> None:
    """Entity IDs without colon separator are reported as failed."""
    resp = client.post(
        "/intelligence/entities/bulk",
        json={
            "entityIds": ["bad_format", "wallet:0xAAA"],
            "action": "export",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["processed"] == 1
    assert body["failed"] == 1
    assert "bad_format" in body["errors"][0]


def test_bulk_status_update_missing_status(client: TestClient) -> None:
    """Status update without status field reports failures."""
    resp = client.post(
        "/intelligence/entities/bulk",
        json={
            "entityIds": ["wallet:0xAAA"],
            "action": "status_update",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["failed"] == 1
