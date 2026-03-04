"""Unit tests for the SSI guidance API — Phase 3C.

Tests cover:
* ``POST /events/ssi/{scan_id}/guidance`` — submit analyst guidance commands.
* ``GET /events/ssi/{scan_id}/guidance/pending`` — poll pending commands.
* ``POST /events/ssi/{scan_id}/guidance/{command_id}/ack`` — acknowledge commands.

Authentication is passed via the ``X-API-KEY`` header accepted in local /
dev environments.  The ``build_ssi_events_store`` factory is patched to
avoid any filesystem / database I/O.
"""

from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from i4g.api.app import app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

AUTH_HEADERS = {"X-API-KEY": "dev-analyst-token"}
SCAN_ID = "scan-guidance-001"


@pytest.fixture(autouse=True)
def _reset_rate_limit() -> None:
    """Clear the rate-limit log between tests so counts don't bleed."""
    from i4g.api import app as app_module  # type: ignore[attr-defined]

    with contextlib.suppress(AttributeError):
        app_module.REQUEST_LOG.clear()


def _mock_store() -> MagicMock:
    """Return a ``SsiEventsStore`` mock with guidance methods configured.

    Returns:
        Configured ``MagicMock`` mimicking ``SsiEventsStore``.
    """
    store = MagicMock()
    store.insert_guidance_command.return_value = "cmd-001"
    store.insert_event.return_value = "evt-001"
    store.get_pending_guidance.return_value = [
        {
            "id": "cmd-001",
            "scan_id": SCAN_ID,
            "action": "click",
            "value": "#submit-btn",
            "reason": "Found the submit button",
            "acknowledged": False,
            "created_at": "2026-03-03T10:00:00Z",
        },
    ]
    store.acknowledge_guidance.return_value = True
    return store


# ---------------------------------------------------------------------------
# POST /events/ssi/{scan_id}/guidance
# ---------------------------------------------------------------------------


class TestSubmitGuidance:
    """Tests for the guidance submission endpoint."""

    def test_submit_guidance_returns_accepted(self) -> None:
        """POST with a valid guidance command returns 202 Accepted."""
        mock_store = _mock_store()

        with (
            patch(
                "i4g.api.ssi_events.build_ssi_events_store",
                return_value=mock_store,
            ),
            patch(
                "i4g.api.ssi_events._publish_guidance",
                new=AsyncMock(),
            ),
            patch(
                "i4g.api.ssi_events._publish_events",
                new=AsyncMock(),
            ),
        ):
            client = TestClient(app)
            resp = client.post(
                f"/events/ssi/{SCAN_ID}/guidance",
                json={"action": "click", "value": "#btn", "reason": "test"},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 202
        body = resp.json()
        assert body["id"] == "cmd-001"
        assert body["action"] == "click"
        assert body["status"] == "pending"
        mock_store.insert_guidance_command.assert_called_once_with(
            scan_id=SCAN_ID,
            action="click",
            value="#btn",
            reason="test",
        )

    def test_submit_guidance_invalid_action_returns_422(self) -> None:
        """POST with an invalid guidance action returns 422."""
        mock_store = _mock_store()

        with (
            patch(
                "i4g.api.ssi_events.build_ssi_events_store",
                return_value=mock_store,
            ),
            patch(
                "i4g.api.ssi_events._publish_guidance",
                new=AsyncMock(),
            ),
        ):
            client = TestClient(app)
            resp = client.post(
                f"/events/ssi/{SCAN_ID}/guidance",
                json={"action": "invalid_action", "value": "x"},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 422
        mock_store.insert_guidance_command.assert_not_called()

    def test_submit_guidance_no_value_defaults_empty(self) -> None:
        """POST without ``value`` or ``reason`` succeeds with empty defaults."""
        mock_store = _mock_store()

        with (
            patch(
                "i4g.api.ssi_events.build_ssi_events_store",
                return_value=mock_store,
            ),
            patch(
                "i4g.api.ssi_events._publish_guidance",
                new=AsyncMock(),
            ),
            patch(
                "i4g.api.ssi_events._publish_events",
                new=AsyncMock(),
            ),
        ):
            client = TestClient(app)
            resp = client.post(
                f"/events/ssi/{SCAN_ID}/guidance",
                json={"action": "continue"},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 202
        body = resp.json()
        assert body["action"] == "continue"
        mock_store.insert_guidance_command.assert_called_once_with(
            scan_id=SCAN_ID,
            action="continue",
            value="",
            reason="",
        )


# ---------------------------------------------------------------------------
# GET /events/ssi/{scan_id}/guidance/pending
# ---------------------------------------------------------------------------


class TestGetPendingGuidance:
    """Tests for pending guidance polling."""

    def test_get_pending_returns_commands(self) -> None:
        """GET returns pending guidance commands."""
        mock_store = _mock_store()

        with patch(
            "i4g.api.ssi_events.build_ssi_events_store",
            return_value=mock_store,
        ):
            client = TestClient(app)
            resp = client.get(
                f"/events/ssi/{SCAN_ID}/guidance/pending",
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert len(body["commands"]) == 1
        assert body["commands"][0]["action"] == "click"
        assert body["commands"][0]["value"] == "#submit-btn"
        mock_store.get_pending_guidance.assert_called_once_with(SCAN_ID, limit=10)

    def test_get_pending_empty(self) -> None:
        """GET returns empty list when no pending commands."""
        mock_store = _mock_store()
        mock_store.get_pending_guidance.return_value = []

        with patch(
            "i4g.api.ssi_events.build_ssi_events_store",
            return_value=mock_store,
        ):
            client = TestClient(app)
            resp = client.get(
                f"/events/ssi/{SCAN_ID}/guidance/pending",
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 0
        assert body["commands"] == []

    def test_get_pending_custom_limit(self) -> None:
        """GET respects the ``limit`` query parameter."""
        mock_store = _mock_store()

        with patch(
            "i4g.api.ssi_events.build_ssi_events_store",
            return_value=mock_store,
        ):
            client = TestClient(app)
            resp = client.get(
                f"/events/ssi/{SCAN_ID}/guidance/pending?limit=5",
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        mock_store.get_pending_guidance.assert_called_once_with(SCAN_ID, limit=5)


# ---------------------------------------------------------------------------
# POST /events/ssi/{scan_id}/guidance/{command_id}/ack
# ---------------------------------------------------------------------------


class TestAcknowledgeGuidance:
    """Tests for guidance command acknowledgement."""

    def test_acknowledge_returns_success(self) -> None:
        """POST acknowledge returns 200 when command exists."""
        mock_store = _mock_store()

        with patch(
            "i4g.api.ssi_events.build_ssi_events_store",
            return_value=mock_store,
        ):
            client = TestClient(app)
            resp = client.post(
                f"/events/ssi/{SCAN_ID}/guidance/cmd-001/ack",
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["acknowledged"] is True
        assert body["id"] == "cmd-001"
        mock_store.acknowledge_guidance.assert_called_once_with("cmd-001")

    def test_acknowledge_not_found_returns_404(self) -> None:
        """POST acknowledge returns 404 when command does not exist."""
        mock_store = _mock_store()
        mock_store.acknowledge_guidance.return_value = False

        with patch(
            "i4g.api.ssi_events.build_ssi_events_store",
            return_value=mock_store,
        ):
            client = TestClient(app)
            resp = client.post(
                f"/events/ssi/{SCAN_ID}/guidance/nonexistent/ack",
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 404
