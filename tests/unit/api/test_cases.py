from fastapi.testclient import TestClient

from i4g.api.app import app

client = TestClient(app)


def test_get_case_detail_not_in_db():
    """Cases not in the DB return 404."""
    case_id = "case-nonexistent-xyz"
    response = client.get(f"/cases/{case_id}")
    assert response.status_code == 404


def test_get_case_dynamic_not_found():
    """Non-existent case IDs return 404."""
    case_id = "case-dynamic-999"
    response = client.get(f"/cases/{case_id}")
    assert response.status_code == 404


def test_get_case_not_found():
    """Test 404 for unknown case ID format."""
    response = client.get("/cases/unknown-id-format")
    assert response.status_code == 404
