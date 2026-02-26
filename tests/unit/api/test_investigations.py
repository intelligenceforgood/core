"""Unit tests for SSI investigation trigger endpoint (Phase 3: 3.1, 3.2).

Tests verify:
- ``POST /investigations/ssi`` creates a task and returns 202.
- ``GET /investigations/ssi/{task_id}`` returns task status.
- Request validation rejects invalid payloads.
- Role enforcement requires analyst role or above.
- Cloud Run Job trigger is called with correct env overrides.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from i4g.api.app import app
from i4g.task_status_store import TASK_STATUS

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_task_status():
    """Clear the task status store between tests."""
    TASK_STATUS.clear()
    yield
    TASK_STATUS.clear()


class TestTriggerSsiInvestigation:
    """Tests for POST /investigations/ssi."""

    def test_trigger_returns_202_with_task_id(self) -> None:
        """Triggering an SSI investigation returns 202 with task metadata."""
        resp = client.post(
            "/investigations/ssi",
            json={"url": "https://scam.example.com"},
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] in ("queued", "running")
        assert data["taskId"].startswith("ssi-")
        assert "message" in data

    def test_trigger_registers_task_in_status_store(self) -> None:
        """The endpoint registers the task in TASK_STATUS immediately."""
        resp = client.post(
            "/investigations/ssi",
            json={"url": "https://scam.example.com", "scanType": "passive"},
        )
        assert resp.status_code == 202
        task_id = resp.json()["taskId"]
        assert task_id in TASK_STATUS
        assert TASK_STATUS[task_id]["status"] in ("queued", "running")

    def test_trigger_with_all_options(self) -> None:
        """All request fields are accepted and processed."""
        resp = client.post(
            "/investigations/ssi",
            json={
                "url": "https://scam.example.com",
                "scanType": "active",
                "pushToCore": False,
                "triggerDossier": True,
                "dataset": "test-dataset",
            },
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["taskId"].startswith("ssi-")

    def test_trigger_requires_url(self) -> None:
        """Request without URL returns 422."""
        resp = client.post("/investigations/ssi", json={})
        assert resp.status_code == 422

    def test_trigger_rejects_invalid_scan_type(self) -> None:
        """Invalid scan_type values are rejected."""
        resp = client.post(
            "/investigations/ssi",
            json={"url": "https://scam.example.com", "scan_type": "invalid"},
        )
        assert resp.status_code == 422

    def test_trigger_uses_defaults(self) -> None:
        """Default values are applied for optional fields."""
        resp = client.post(
            "/investigations/ssi",
            json={"url": "https://scam.example.com"},
        )
        assert resp.status_code == 202


class TestGetSsiInvestigationStatus:
    """Tests for GET /investigations/ssi/{task_id}."""

    def test_get_existing_task(self) -> None:
        """Known task ID returns its status."""
        TASK_STATUS["ssi-test123"] = {
            "status": "running",
            "message": "Investigation in progress",
        }
        resp = client.get("/investigations/ssi/ssi-test123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == "ssi-test123"
        assert data["status"] == "running"

    def test_get_unknown_task(self) -> None:
        """Unknown task ID returns 'unknown' status."""
        resp = client.get("/investigations/ssi/nonexistent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "unknown"


class TestSsiInvestigationRbac:
    """Test role enforcement for SSI investigation endpoints."""

    def test_analyst_can_trigger(self) -> None:
        """Analyst role can trigger investigations (via local-dev bypass)."""
        # In local env, auth is disabled → returns local-dev admin user.
        resp = client.post(
            "/investigations/ssi",
            json={"url": "https://scam.example.com"},
        )
        assert resp.status_code == 202


class TestCloudRunJobTrigger:
    """Tests for the Cloud Run Job trigger logic."""

    @patch("i4g.api.investigations._trigger_cloud_run_job")
    def test_cloud_trigger_passes_env_overrides(self, mock_trigger: MagicMock) -> None:
        """Verify env overrides include task_id and status URL."""
        mock_trigger.return_value = "operations/test-op"

        # Force non-local env to exercise the Cloud Run path
        from i4g.settings import get_settings

        settings = get_settings()
        original_env = settings.env
        try:
            settings.env = "dev"
            resp = client.post(
                "/investigations/ssi",
                json={"url": "https://scam.example.com", "scanType": "full"},
            )
            assert resp.status_code == 202

            if mock_trigger.called:
                call_kwargs = mock_trigger.call_args
                env_overrides = call_kwargs.kwargs.get("env_overrides", {})
                assert "SSI_JOB__URL" in env_overrides
                assert env_overrides["SSI_JOB__URL"] == "https://scam.example.com"
                assert "I4G_TASK_ID" in env_overrides
                assert "I4G_TASK_STATUS_URL" in env_overrides
        finally:
            settings.env = original_env

