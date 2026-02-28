import pytest
from fastapi.testclient import TestClient

from i4g.api.app import app
from i4g.task_status_store import TASK_STATUS

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean_task_status():
    """Clear TASK_STATUS between tests to avoid cross-contamination."""
    yield
    TASK_STATUS.clear()


def test_get_task_status_unknown():
    """Test retrieving the status of an unknown task."""
    task_id = "unknown_task"
    response = client.get(f"/tasks/{task_id}")
    assert response.status_code == 200
    assert response.json() == {
        "taskId": task_id,
        "status": "unknown",
        "message": "Task not found",
    }


def test_update_task_status():
    """Test updating the status of a task."""
    task_id = "test_task"
    payload = {"status": "in_progress", "message": "Generating report..."}

    # Update the task status
    response = client.post(f"/tasks/{task_id}/update", json=payload)
    assert response.status_code == 200
    assert response.json() == {"taskId": task_id, "updated": True}

    # Verify the updated status
    response = client.get(f"/tasks/{task_id}")
    assert response.status_code == 200
    assert response.json() == {"taskId": task_id, **payload}


def test_update_task_status_with_ssi_completion():
    """Test that SSI Job completion payload (non-string values) is accepted and returned."""
    task_id = "ssi_task_123"
    payload = {
        "status": "completed",
        "message": "Investigation completed in 45.2s",
        "investigation_id": "scan-uuid-abc",
        "risk_score": 85.5,
        "case_id": "case-uuid-xyz",
        "duration_seconds": 45.2,
    }

    # Update with mixed types (str, float, None)
    response = client.post(f"/tasks/{task_id}/update", json=payload)
    assert response.status_code == 200

    # Verify all fields are returned (camelCase)
    response = client.get(f"/tasks/{task_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["taskId"] == task_id
    assert data["status"] == "completed"
    assert data["investigationId"] == "scan-uuid-abc"
    assert data["riskScore"] == 85.5
    assert data["caseId"] == "case-uuid-xyz"
    assert data["durationSeconds"] == 45.2


def test_update_task_status_with_null_values():
    """Test that payload with None values (e.g. case_id=None) is accepted."""
    task_id = "ssi_task_null"
    payload = {
        "status": "completed",
        "message": "Done",
        "investigation_id": "scan-uuid",
        "risk_score": 90.0,
        "case_id": None,
        "duration_seconds": 30.0,
    }

    response = client.post(f"/tasks/{task_id}/update", json=payload)
    assert response.status_code == 200

    response = client.get(f"/tasks/{task_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["investigationId"] == "scan-uuid"
    # case_id is None → excluded by response_model_exclude_none
    assert "caseId" not in data
