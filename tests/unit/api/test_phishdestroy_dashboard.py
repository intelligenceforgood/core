"""Unit tests for the PhishDestroy /dashboard API endpoints."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from i4g.api.auth import require_token


@pytest.fixture()
def client():
    from i4g.api.app import app

    app.dependency_overrides[require_token] = lambda: {"username": "test_user", "role": "analyst"}
    yield TestClient(app)
    app.dependency_overrides.pop(require_token, None)


@patch("i4g.api.phishdestroy_dashboard.build_threat_actor_store")
@patch("i4g.api.phishdestroy_dashboard.build_domain_discovery_store")
def test_get_dashboard_stats(mock_domain_store, mock_actor_store, client):
    mock_actor_store.return_value.count_actors.return_value = 10
    mock_domain_store.return_value.count_recent_matches.return_value = 25

    resp = client.get("/phishdestroy/dashboard/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["totalActors"] == 10
    assert data["activeDomains"] == 25


@patch("i4g.api.phishdestroy_dashboard.build_threat_actor_store")
@patch("i4g.api.phishdestroy_dashboard.build_actor_identity_store")
@patch("i4g.api.phishdestroy_dashboard.build_financial_damage_store")
def test_get_dashboard_actors(mock_damage_store, mock_identity_store, mock_actor_store, client):
    mock_actor_store.return_value.list_actors.return_value = [
        {"actor_id": "a1", "campaign_id": "c1", "display_name": "Actor 1"},
    ]
    mock_identity_store.return_value.list_by_actor.return_value = [
        {"handle": "alias1"},
        {"handle": "alias2"},
    ]
    mock_damage_store.return_value.totals_by_currency.return_value = {
        "USD": {"claimed": 100.0, "confirmed": 50.0},
        "EUR": {"claimed": 200.0, "confirmed": 200.0},
    }

    resp = client.get("/phishdestroy/dashboard/actors")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    actor = data[0]
    assert actor["name"] == "Actor 1"
    assert actor["aliases"] == ["alias1", "alias2"]
    assert actor["stolenAmount"] == 300.0
    assert actor["domains"] == []
    assert actor["status"] == "active"


@patch("i4g.api.phishdestroy_dashboard.build_actor_identity_store")
@patch("i4g.api.phishdestroy_dashboard.build_actor_identity_edge_store")
def test_get_dashboard_graph(mock_edge_store, mock_identity_store, client):
    mock_identity_store.return_value.list_all_identities.return_value = [
        {"identity_id": "i1", "handle": "node1"},
        {"identity_id": "i2", "handle": "node2"},
    ]
    mock_edge_store.return_value.list_all_edges.return_value = [
        {"source_identity_id": "i1", "target_identity_id": "i2", "weight": 2.5}
    ]

    resp = client.get("/phishdestroy/dashboard/graph")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["nodes"]) == 2
    assert data["nodes"][0]["id"] == "i1"
    assert data["nodes"][0]["label"] == "node1"
    assert len(data["links"]) == 1
    assert data["links"][0]["source"] == "i1"
    assert data["links"][0]["target"] == "i2"
    assert data["links"][0]["value"] == 2
