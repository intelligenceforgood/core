"""Unit tests for the SSI events API — Phase 3B.

Tests cover:
* ``POST /events/ssi/{scan_id}`` — batch ingestion with store and Redis mocked.
* ``GET /events/ssi/{scan_id}`` — chronological event replay.
* ``GET /events/ssi/{scan_id}/stream`` — SSE header / MIME verification.

Authentication is passed via the ``X-API-KEY`` header accepted in local /
dev environments.  The ``build_ssi_events_store`` factory is patched to
avoid any filesystem / database I/O.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from i4g.api.app import app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

AUTH_HEADERS = {"X-API-KEY": "dev-analyst-token"}
SCAN_ID = "scan-abc-123"


@pytest.fixture(autouse=True)
def _reset_rate_limit() -> None:
    """Clear the rate-limit log between tests so counts don't bleed."""
    from i4g.api import app as app_module  # type: ignore[attr-defined]

    try:
        app_module.REQUEST_LOG.clear()
    except AttributeError:
        pass


def _mock_store(events: list[dict] | None = None) -> MagicMock:
    """Return a ``SsiEventsStore`` mock with configurable get_events output.

    Args:
        events: Pre-seeded list of event dicts returned by ``get_events``.

    Returns:
        Configured ``MagicMock`` mimicking ``SsiEventsStore``.
    """
    store = MagicMock()
    store.insert_event_batch.return_value = ["id-1", "id-2"]
    store.get_events.return_value = events or []
    return store


# ---------------------------------------------------------------------------
# POST /events/ssi/{scan_id}
# ---------------------------------------------------------------------------


class TestIngestSsiEvents:
    """Tests for the event ingestion endpoint."""

    def test_ingest_batch_returns_accepted(self) -> None:
        """POST with valid events returns 202 Accepted and an ``inserted`` count."""
        mock_store = _mock_store()

        with (
            patch(
                "i4g.api.ssi_events.build_ssi_events_store",
                return_value=mock_store,
            ),
            patch(
                "i4g.api.ssi_events._publish_events",
                new=AsyncMock(),
            ),
        ):
            client = TestClient(app)
            payload = {
                "events": [
                    {
                        "eventType": "state_changed",
                        "timestamp": "2026-01-01T00:00:00Z",
                        "investigationId": SCAN_ID,
                        "data": {"state": "navigating"},
                    },
                    {
                        "eventType": "wallet_found",
                        "timestamp": "2026-01-01T00:01:00Z",
                        "investigationId": SCAN_ID,
                        "data": {"address": "0xABC"},
                    },
                ]
            }
            resp = client.post(
                f"/events/ssi/{SCAN_ID}",
                json=payload,
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 202
        body = resp.json()
        assert body["inserted"] == 2
        # Plain dict return type — no CamelModel alias, stays snake_case.
        assert body["scan_id"] == SCAN_ID
        mock_store.insert_event_batch.assert_called_once()

    def test_ingest_empty_batch_returns_zero(self) -> None:
        """POST with an empty events list returns 202 with inserted=0."""
        mock_store = _mock_store()

        with (
            patch(
                "i4g.api.ssi_events.build_ssi_events_store",
                return_value=mock_store,
            ),
            patch(
                "i4g.api.ssi_events._publish_events",
                new=AsyncMock(),
            ),
        ):
            client = TestClient(app)
            resp = client.post(
                f"/events/ssi/{SCAN_ID}",
                json={"events": []},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 202
        body = resp.json()
        assert body["inserted"] == 0
        # Store should not be called for an empty batch.
        mock_store.insert_event_batch.assert_not_called()

    @pytest.mark.skip(reason="Auth enforcement depends on I4G_ENV; skipped in local dev mode")
    def test_ingest_requires_auth(self) -> None:
        """POST without an API key returns 401 or 403 when auth is enforced."""
        with (
            patch("i4g.api.ssi_events.build_ssi_events_store"),
            patch("i4g.api.ssi_events._publish_events", new=AsyncMock()),
        ):
            client = TestClient(app)
            resp = client.post(
                f"/events/ssi/{SCAN_ID}",
                json={"events": []},
            )

        assert resp.status_code in {401, 403}

    def test_ingest_store_error_returns_500(self) -> None:
        """POST returns 500 when the store raises an unexpected exception."""
        mock_store = MagicMock()
        mock_store.insert_event_batch.side_effect = RuntimeError("DB error")

        with (
            patch(
                "i4g.api.ssi_events.build_ssi_events_store",
                return_value=mock_store,
            ),
            patch(
                "i4g.api.ssi_events._publish_events",
                new=AsyncMock(),
            ),
        ):
            client = TestClient(app)
            payload = {
                "events": [
                    {
                        "eventType": "state_changed",
                        "data": {},
                    }
                ]
            }
            resp = client.post(
                f"/events/ssi/{SCAN_ID}",
                json=payload,
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# GET /events/ssi/{scan_id}
# ---------------------------------------------------------------------------


class TestGetSsiEvents:
    """Tests for the event replay / list endpoint."""

    def test_replay_returns_all_events(self) -> None:
        """GET returns all stored events in the expected schema."""
        stored = [
            {
                "id": "evt-1",
                "scan_id": SCAN_ID,
                "event_type": "state_changed",
                "timestamp": "2026-01-01T00:00:00+00:00",
                "data_json": {"state": "navigating"},
                "screenshot_url": None,
                "created_at": "2026-01-01T00:00:00+00:00",
            },
        ]
        mock_store = _mock_store(events=stored)

        with patch(
            "i4g.api.ssi_events.build_ssi_events_store",
            return_value=mock_store,
        ):
            client = TestClient(app)
            resp = client.get(f"/events/ssi/{SCAN_ID}", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["scanId"] == SCAN_ID
        assert len(body["items"]) == 1
        # data_json should be renamed to data in the wire format.
        item = body["items"][0]
        assert "data" in item
        assert item["data"]["state"] == "navigating"

    def test_replay_empty_returns_zero(self) -> None:
        """GET for a scan with no events returns count=0 and an empty list."""
        mock_store = _mock_store(events=[])

        with patch(
            "i4g.api.ssi_events.build_ssi_events_store",
            return_value=mock_store,
        ):
            client = TestClient(app)
            resp = client.get(f"/events/ssi/{SCAN_ID}", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 0
        assert body["items"] == []

    @pytest.mark.skip(reason="Auth enforcement depends on I4G_ENV; skipped in local dev mode")
    def test_replay_requires_auth(self) -> None:
        """GET without an API key returns 401 or 403 when auth is enforced."""
        with patch("i4g.api.ssi_events.build_ssi_events_store"):
            client = TestClient(app)
            resp = client.get(f"/events/ssi/{SCAN_ID}")

        assert resp.status_code in {401, 403}


# ---------------------------------------------------------------------------
# GET /events/ssi/{scan_id}/stream
# ---------------------------------------------------------------------------


class TestStreamSsiEvents:
    """Smoke tests for the SSE stream endpoint."""

    def test_stream_content_type_header(self) -> None:
        """GET /stream returns Content-Type: text/event-stream."""
        # Provide a trivial DB-polling generator that closes immediately.
        async def _noop_generator() -> None:
            # Yield nothing — connection closes immediately.
            return
            yield  # Make this an async generator.

        mock_store = _mock_store(events=[])

        with (
            patch(
                "i4g.api.ssi_events.build_ssi_events_store",
                return_value=mock_store,
            ),
            patch(
                "i4g.api.ssi_events._get_redis_client",
                return_value=None,
            ),
            patch(
                "i4g.api.ssi_events._stream_from_db",
                return_value=_noop_generator(),
            ),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            with client.stream(
                "GET",
                f"/events/ssi/{SCAN_ID}/stream",
                headers=AUTH_HEADERS,
            ) as resp:
                ct = resp.headers.get("content-type", "")
                assert "text/event-stream" in ct
