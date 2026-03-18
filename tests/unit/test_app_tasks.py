from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from i4g.api.app import _stale_running_scan, app
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


# ---------------------------------------------------------------------------
# Staleness detection unit tests
# ---------------------------------------------------------------------------


def test_stale_running_scan_detects_old_scan() -> None:
    """A scan whose updated_at is >2 h ago should be considered stale."""
    old_ts = datetime.now(UTC) - timedelta(hours=3)
    assert _stale_running_scan({"updated_at": old_ts}) is True


def test_stale_running_scan_recent_scan() -> None:
    """A scan updated recently is NOT stale."""
    recent_ts = datetime.now(UTC) - timedelta(minutes=10)
    assert _stale_running_scan({"updated_at": recent_ts}) is False


def test_stale_running_scan_falls_back_to_started_at() -> None:
    """When updated_at is absent the fallback is started_at."""
    old_ts = datetime.now(UTC) - timedelta(hours=3)
    assert _stale_running_scan({"started_at": old_ts}) is True


def test_stale_running_scan_no_timestamp() -> None:
    """A scan with no timestamp columns is not considered stale (safe default)."""
    assert _stale_running_scan({}) is False


def test_get_task_status_auto_fails_stale_running_scan() -> None:
    """GET /tasks/{task_id} must return 'failed' for a stale orphaned scan."""
    task_id = "stale-scan-uuid"
    stale_ts = datetime.now(UTC) - timedelta(hours=3)
    fake_scan = {
        "scan_id": task_id,
        "url": "https://example-scam.com",
        "status": "running",
        "updated_at": stale_ts,
        "risk_score": None,
        "case_id": None,
        "duration_seconds": None,
        "error_message": None,
    }

    mock_store = MagicMock()
    mock_store.get_scan.return_value = fake_scan

    with patch("i4g.services.factories.build_ssi_store", return_value=mock_store):
        response = client.get(f"/tasks/{task_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert "interrupted" in data["message"].lower()
    # The store should have been told to persist the failure.
    mock_store.update_scan.assert_called_once_with(
        task_id,
        status="failed",
        error_message="Investigation was interrupted (service restarted while it was running).",
    )


def test_get_task_status_scan_id_fallback_when_db_fails() -> None:
    """When TASK_STATUS has scan_id but DB lookup fails, investigationId must still be populated."""
    task_id = "task-with-scan"
    scan_id = "scan-uuid-fallback"
    TASK_STATUS[task_id] = {
        "status": "running",
        "message": "Investigation running",
        "scan_id": scan_id,
        "url": "https://example.com",
    }

    mock_store = MagicMock()
    mock_store.get_scan.side_effect = Exception("DB unavailable")

    with patch("i4g.services.factories.build_ssi_store", return_value=mock_store):
        response = client.get(f"/tasks/{task_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["investigationId"] == scan_id
    assert data["status"] == "running"
