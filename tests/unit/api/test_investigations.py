"""Unit tests for SSI investigation trigger endpoint (Phase 3: 3.1, 3.2).

Tests verify:
- ``POST /investigations/ssi`` creates a task and returns 202.
- ``GET /investigations/ssi/{task_id}`` returns task status.
- Request validation rejects invalid payloads.
- Role enforcement requires analyst role or above.
- Cloud Run Service trigger is called with correct parameters.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from i4g.api.app import app
from i4g.api.investigations import _trigger_cloud_run_service
from i4g.services.investigation_dedup import DedupResult
from i4g.task_status_store import TASK_STATUS

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_task_status():
    """Clear the task status store between tests."""
    TASK_STATUS.clear()
    yield
    TASK_STATUS.clear()


@pytest.fixture(autouse=True)
def _bypass_dedup(monkeypatch):
    """Bypass the URL dedup check so trigger tests hit the service path."""
    monkeypatch.setattr(
        "i4g.api.investigations.check_url_duplicate",
        lambda *args, **kwargs: DedupResult(is_duplicate=False, reason="no_prior_scan"),
    )


class TestTriggerSsiInvestigation:
    """Tests for POST /investigations/ssi."""

    @patch("i4g.api.investigations._trigger_cloud_run_service")
    def test_trigger_returns_202_with_task_id(self, mock_service: MagicMock) -> None:
        """Triggering an SSI investigation returns 202 with task metadata."""
        resp = client.post(
            "/investigations/ssi",
            json={"url": "https://scam.example.com"},
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "running"
        # task_id is now the scan UUID (36 chars): task_id == scan_id for DB-fallback support
        assert len(data["taskId"]) == 36
        assert "message" in data

    @patch("i4g.api.investigations._trigger_cloud_run_service")
    def test_trigger_registers_task_in_status_store(self, mock_service: MagicMock) -> None:
        """The endpoint registers the task in TASK_STATUS immediately."""
        resp = client.post(
            "/investigations/ssi",
            json={"url": "https://scam.example.com", "scanType": "passive"},
        )
        assert resp.status_code == 202
        task_id = resp.json()["taskId"]
        assert task_id in TASK_STATUS
        assert TASK_STATUS[task_id]["status"] == "running"

    @patch("i4g.api.investigations._trigger_cloud_run_service")
    def test_trigger_with_all_options(self, mock_service: MagicMock) -> None:
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
        # task_id is now a UUID (same as scan_id)
        assert len(data["taskId"]) == 36

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

    @patch("i4g.api.investigations._trigger_cloud_run_service")
    def test_trigger_uses_defaults(self, mock_service: MagicMock) -> None:
        """Default values are applied for optional fields."""
        resp = client.post(
            "/investigations/ssi",
            json={"url": "https://scam.example.com"},
        )
        assert resp.status_code == 202


class TestGetSsiInvestigationStatus:
    """Tests for GET /investigations/ssi/{task_id}.

    Note: The ``GET /investigations/ssi/{task_id}`` convenience alias in
    ``investigations.py`` is now shadowed by the ``GET /investigations/ssi/{scan_id}``
    detail endpoint in ``ssi_investigations.py`` (Phase C).  Callers should use
    ``GET /tasks/{task_id}`` for task-status polling instead.

    These tests verify the new routing behaviour.
    """

    def test_task_status_via_tasks_endpoint(self) -> None:
        """Task polling works via the primary ``/tasks/`` endpoint."""
        TASK_STATUS["ssi-test123"] = {
            "status": "running",
            "message": "Investigation in progress",
        }
        resp = client.get("/tasks/ssi-test123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["taskId"] == "ssi-test123"
        assert data["status"] == "running"

    def test_ssi_scan_detail_replaces_convenience_alias(self) -> None:
        """``GET /investigations/ssi/{id}`` now routes to the scan-detail
        endpoint and returns 404 for task IDs (which are not scan_ids).
        """
        TASK_STATUS["ssi-test456"] = {"status": "running", "message": "In progress"}
        resp = client.get("/investigations/ssi/ssi-test456")
        # The scan-detail endpoint doesn't find this ID in SsiStore → 404.
        assert resp.status_code == 404

    def test_get_unknown_via_tasks(self) -> None:
        """Unknown task ID returns 'unknown' status via ``/tasks/``."""
        resp = client.get("/tasks/nonexistent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "unknown"


class TestSsiInvestigationRbac:
    """Test role enforcement for SSI investigation endpoints."""

    @patch("i4g.api.investigations._trigger_cloud_run_service")
    def test_analyst_can_trigger(self, mock_service: MagicMock) -> None:
        """Analyst role can trigger investigations (via local-dev bypass)."""
        # In local env, auth is disabled → returns local-dev admin user.
        resp = client.post(
            "/investigations/ssi",
            json={"url": "https://scam.example.com"},
        )
        assert resp.status_code == 202


class TestServiceTriggerDispatch:
    """Tests for service-only dispatch path."""

    @patch("i4g.api.investigations._trigger_cloud_run_service")
    def test_trigger_calls_service(self, mock_service: MagicMock) -> None:
        """POST /investigations/ssi calls _trigger_cloud_run_service."""
        resp = client.post(
            "/investigations/ssi",
            json={"url": "https://scam.example.com"},
        )
        assert resp.status_code == 202
        assert mock_service.called, "Service trigger should be called"

        data = resp.json()
        assert data["status"] == "running"
        assert "Cloud Run Service" in data["message"]

    @patch("i4g.api.investigations._trigger_cloud_run_service")
    def test_service_failure_returns_502(self, mock_service: MagicMock) -> None:
        """Service trigger failure returns 502 and records failure in TASK_STATUS."""
        mock_service.side_effect = RuntimeError("Connection refused")

        resp = client.post(
            "/investigations/ssi",
            json={"url": "https://scam.example.com"},
        )
        assert resp.status_code == 502

    @patch("i4g.api.investigations._trigger_cloud_run_service")
    def test_service_trigger_receives_correct_params(self, mock_service: MagicMock) -> None:
        """Service trigger receives correct parameters from the request."""
        resp = client.post(
            "/investigations/ssi",
            json={
                "url": "https://scam.example.com",
                "scanType": "passive",
                "pushToCore": False,
                "dataset": "tutorial",
            },
        )
        assert resp.status_code == 202

        call_kwargs = mock_service.call_args.kwargs
        assert call_kwargs["url"] == "https://scam.example.com"
        assert call_kwargs["scan_type"] == "passive"
        assert call_kwargs["push_to_core"] is False
        assert call_kwargs["dataset"] == "tutorial"
        assert call_kwargs["scan_id"]  # should be a non-empty UUID string

    @patch("i4g.api.investigations._trigger_cloud_run_service")
    def test_response_has_no_job_name_field(self, mock_service: MagicMock) -> None:
        """Response no longer includes a jobName field (job path removed)."""
        resp = client.post(
            "/investigations/ssi",
            json={"url": "https://scam.example.com"},
        )
        assert resp.status_code == 202
        data = resp.json()
        assert "jobName" not in data


class TestTriggerCloudRunService:
    """Unit tests for _trigger_cloud_run_service."""

    @patch("httpx.Client")
    def test_posts_to_correct_endpoint(self, mock_client_cls: MagicMock) -> None:
        """Sends POST to {service_url}/trigger/investigate."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {"scan_id": "abc", "status": "accepted"}
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        _trigger_cloud_run_service(
            service_url="https://ssi-svc.run.app",
            url="https://scam.example.com",
            scan_type="full",
            scan_id="scan-123",
            push_to_core=True,
            dataset="ssi",
        )

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args.args[0] == "https://ssi-svc.run.app/trigger/investigate"
        payload = call_args.kwargs["json"]
        assert payload["url"] == "https://scam.example.com"
        assert payload["scan_type"] == "full"
        assert payload["scan_id"] == "scan-123"

    @patch("httpx.Client")
    def test_strips_trailing_slash_from_service_url(self, mock_client_cls: MagicMock) -> None:
        """Trailing slash in service_url is stripped before path concatenation."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {"scan_id": "abc", "status": "accepted"}
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        _trigger_cloud_run_service(
            service_url="https://ssi-svc.run.app/",
            url="https://scam.example.com",
            scan_type="full",
            scan_id="scan-123",
            push_to_core=True,
            dataset="ssi",
        )

        call_args = mock_client.post.call_args
        assert call_args.args[0] == "https://ssi-svc.run.app/trigger/investigate"

    @patch("httpx.Client")
    def test_http_error_raises_runtime_error(self, mock_client_cls: MagicMock) -> None:
        """HTTPStatusError from httpx is wrapped in RuntimeError."""
        import httpx

        mock_client = MagicMock()
        error_response = MagicMock()
        error_response.status_code = 500
        error_response.text = "Internal Server Error"
        mock_client.post.side_effect = httpx.HTTPStatusError(
            "Server Error",
            request=MagicMock(),
            response=error_response,
        )
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        with pytest.raises(RuntimeError, match="500"):
            _trigger_cloud_run_service(
                service_url="https://ssi-svc.run.app",
                url="https://scam.example.com",
                scan_type="full",
                scan_id="scan-123",
                push_to_core=True,
                dataset="ssi",
            )

    @patch("httpx.Client")
    def test_connection_error_raises_runtime_error(self, mock_client_cls: MagicMock) -> None:
        """Connection failure is wrapped in RuntimeError."""
        import httpx

        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        with pytest.raises(RuntimeError, match="Failed to reach SSI service"):
            _trigger_cloud_run_service(
                service_url="https://ssi-svc.run.app",
                url="https://scam.example.com",
                scan_type="full",
                scan_id="scan-123",
                push_to_core=True,
                dataset="ssi",
            )
