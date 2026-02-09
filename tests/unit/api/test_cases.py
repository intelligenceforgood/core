import pytest
from fastapi.testclient import TestClient
from i4g.api.app import app

client = TestClient(app)


def test_get_case_detail_success():
    """Test retrieving a mock case detail."""
    # Using a known ID from the MOCK_CASES or one that triggers the fallback
    case_id = "case-482"  # From the static list
    response = client.get(f"/cases/{case_id}")

    assert response.status_code == 200
    data = response.json()

    assert data["id"] == case_id
    assert "artifacts" in data
    assert "timeline" in data
    assert "graph_nodes" in data
    assert "graph_links" in data

    # Check specific mock data structure
    assert len(data["artifacts"]) >= 2
    assert data["artifacts"][0]["type"] == "document"


def test_get_case_dynamic_mock():
    """Test that case IDs not in the static list return 404."""
    case_id = "case-dynamic-999"
    response = client.get(f"/cases/{case_id}")
    assert response.status_code == 404


def test_get_case_not_found():
    """Test 404 for unknown case ID format."""
    response = client.get("/cases/unknown-id-format")
    assert response.status_code == 404
