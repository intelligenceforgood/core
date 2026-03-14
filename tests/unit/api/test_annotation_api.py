"""Tests for the annotation CRUD API endpoints (Sprint 4 — S4-15).

Covers POST, GET, PUT, DELETE /intelligence/annotations.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from i4g.api.app import create_app
from i4g.api.intelligence import get_analytics_store, get_annotation_store, get_campaign_store

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

_SAMPLE_ANNOTATION = {
    "annotation_id": "ann-001",
    "target_type": "entity",
    "target_id": "wallet:0xAAA",
    "content": "Suspicious pattern detected",
    "author": "analyst@test.io",
    "created_at": "2025-06-01T10:00:00",
    "updated_at": "2025-06-01T10:00:00",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_analytics_store() -> MagicMock:
    """Create a noop AnalyticsStore mock."""
    return MagicMock()


@pytest.fixture()
def mock_campaign_store() -> MagicMock:
    """Create a noop ThreatCampaignStore mock."""
    return MagicMock()


@pytest.fixture()
def mock_annotation_store() -> MagicMock:
    """Create a mock AnnotationStore with sample data."""
    store = MagicMock()
    store.create_annotation.return_value = "ann-001"
    store.get_annotation.return_value = dict(_SAMPLE_ANNOTATION)
    store.list_annotations.return_value = [dict(_SAMPLE_ANNOTATION)]
    store.update_annotation.return_value = True
    store.delete_annotation.return_value = True
    return store


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
# POST /intelligence/annotations
# ---------------------------------------------------------------------------


def test_create_annotation(client: TestClient, mock_annotation_store: MagicMock) -> None:
    """POST /intelligence/annotations creates and returns annotation."""
    resp = client.post(
        "/intelligence/annotations",
        json={"targetType": "entity", "targetId": "wallet:0xAAA", "content": "Suspicious pattern"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["annotationId"] == "ann-001"
    assert body["targetType"] == "entity"
    mock_annotation_store.create_annotation.assert_called_once()


def test_create_annotation_invalid_target_type(client: TestClient) -> None:
    """POST with invalid target_type returns 400."""
    resp = client.post(
        "/intelligence/annotations",
        json={"targetType": "invalid", "targetId": "x", "content": "test"},
    )
    assert resp.status_code == 400


def test_create_annotation_all_target_types(client: TestClient) -> None:
    """All valid target types (entity, indicator, campaign, case) are accepted."""
    for target_type in ("entity", "indicator", "campaign", "case"):
        resp = client.post(
            "/intelligence/annotations",
            json={"targetType": target_type, "targetId": "test-id", "content": "note"},
        )
        assert resp.status_code == 200, f"Failed for target_type={target_type}"


# ---------------------------------------------------------------------------
# GET /intelligence/annotations
# ---------------------------------------------------------------------------


def test_list_annotations(client: TestClient) -> None:
    """GET /intelligence/annotations returns list."""
    resp = client.get("/intelligence/annotations")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 1
    assert body[0]["annotationId"] == "ann-001"


def test_list_annotations_with_filters(client: TestClient, mock_annotation_store: MagicMock) -> None:
    """GET with target_type and target_id filters forwards to store."""
    client.get("/intelligence/annotations", params={"target_type": "entity", "target_id": "wallet:0xAAA"})
    call_kwargs = mock_annotation_store.list_annotations.call_args.kwargs
    assert call_kwargs["target_type"] == "entity"
    assert call_kwargs["target_id"] == "wallet:0xAAA"


def test_list_annotations_limit(client: TestClient, mock_annotation_store: MagicMock) -> None:
    """GET with limit param forwards to store."""
    client.get("/intelligence/annotations", params={"limit": 50})
    call_kwargs = mock_annotation_store.list_annotations.call_args.kwargs
    assert call_kwargs["limit"] == 50


# ---------------------------------------------------------------------------
# PUT /intelligence/annotations/{id}
# ---------------------------------------------------------------------------


def test_update_annotation(client: TestClient, mock_annotation_store: MagicMock) -> None:
    """PUT /intelligence/annotations/{id} updates content."""
    resp = client.put("/intelligence/annotations/ann-001", json={"content": "Updated note"})
    assert resp.status_code == 200
    mock_annotation_store.update_annotation.assert_called_once_with("ann-001", content="Updated note")


def test_update_annotation_not_found(client: TestClient, mock_annotation_store: MagicMock) -> None:
    """PUT returns 404 when annotation doesn't exist."""
    mock_annotation_store.update_annotation.return_value = False
    resp = client.put("/intelligence/annotations/missing", json={"content": "x"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /intelligence/annotations/{id}
# ---------------------------------------------------------------------------


def test_delete_annotation(client: TestClient, mock_annotation_store: MagicMock) -> None:
    """DELETE /intelligence/annotations/{id} deletes and returns confirmation."""
    resp = client.delete("/intelligence/annotations/ann-001")
    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted"] is True


def test_delete_annotation_not_found(client: TestClient, mock_annotation_store: MagicMock) -> None:
    """DELETE returns 404 when annotation doesn't exist."""
    mock_annotation_store.delete_annotation.return_value = False
    resp = client.delete("/intelligence/annotations/missing")
    assert resp.status_code == 404
