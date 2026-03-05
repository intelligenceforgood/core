"""Unit tests for the feedback API router."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from i4g.api.app import app
from i4g.api.auth import require_token

VALID_BODY = {
    "feedback_id": "dashboard.metrics",
    "feedback_type": "Bug",
    "priority": "P2-Medium",
    "subject": "Metric broken",
    "description": "The active-cases metric shows NaN.",
    "page_url": "https://console.example.com/dashboard",
    "user_agent": "Mozilla/5.0 (Test)",
}


@pytest.fixture(autouse=True)
def _clear_overrides():
    """Reset dependency overrides between tests."""
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def _auth_headers() -> dict[str, str]:
    """Return headers that pass the require_token dependency."""
    from i4g.settings import get_settings

    settings = get_settings()
    return {"x-api-key": settings.api.key}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFeedbackEndpoint:
    """POST /feedback endpoint tests."""

    @patch("i4g.api.feedback._get_service")
    def test_submit_success(self, mock_get_svc: MagicMock) -> None:
        """Successful submission returns 200 with success=true."""
        mock_svc = MagicMock()
        mock_svc.submit.return_value = True
        mock_get_svc.return_value = mock_svc

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/feedback", json=VALID_BODY, headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "thank you" in data["message"].lower()

    @patch("i4g.api.feedback._get_service")
    def test_submit_failure(self, mock_get_svc: MagicMock) -> None:
        """Service failure returns 500."""
        mock_svc = MagicMock()
        mock_svc.submit.return_value = False
        mock_get_svc.return_value = mock_svc

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/feedback", json=VALID_BODY, headers=_auth_headers())
        assert resp.status_code == 500

    def test_submit_no_auth(self) -> None:
        """When require_token raises, the endpoint rejects unauthenticated."""

        def _deny() -> dict:
            raise HTTPException(status_code=401, detail="Not authenticated")

        app.dependency_overrides[require_token] = _deny

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/feedback", json=VALID_BODY)
        assert resp.status_code == 401

    def test_submit_missing_fields(self) -> None:
        """Missing required fields returns 422."""
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/feedback",
            json={"feedback_id": "dashboard.metrics"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 422

    @patch("i4g.api.feedback._get_service")
    def test_submitter_injected_from_auth(self, mock_get_svc: MagicMock) -> None:
        """Submitter comes from the auth context, not the request body."""
        app.dependency_overrides[require_token] = lambda: {
            "email": "analyst@test.io",
            "role": "analyst",
        }

        mock_svc = MagicMock()
        mock_svc.submit.return_value = True
        mock_get_svc.return_value = mock_svc

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/feedback", json=VALID_BODY)
        assert resp.status_code == 200

        call_args = mock_svc.submit.call_args
        payload = call_args[0][0]
        assert payload.submitter == "analyst@test.io"
