"""SSI investigation event store and SSE stream — Phase 3B.

Two endpoints:

* ``POST /events/ssi/{scan_id}`` — SSI service pushes event batches here.
  Events are stored in ``ssi_events`` and published to Redis pub/sub for
  immediate fan-out to live SSE subscribers.

* ``GET /events/ssi/{scan_id}/stream`` — SSE endpoint streamed to the
  browser.  Subscribes to the Redis channel for the scan; falls back to
  polling ``ssi_events`` at 2-second intervals when Redis is unavailable.

* ``GET /events/ssi/{scan_id}`` — Return all stored events for replay on
  the investigation detail page.

Authentication:
  * ``POST`` — accepts either an analyst JWT *or* a bare service token
    issued by the SSI Cloud Run Service (identical OIDC check used elsewhere).
  * ``GET`` — requires the standard analyst JWT.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import Field

from i4g.api.auth import require_token
from i4g.api.camel import CamelModel
from i4g.services.factories import build_ssi_events_store
from i4g.settings import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/events/ssi",
    tags=["ssi-events"],
)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class SsiEventPayload(CamelModel):
    """A single investigation event pushed by the SSI service."""

    event_type: str
    timestamp: str | None = None
    investigation_id: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    # Forwarded screenshot URL (unused for inline base64 — kept for future GCS path).
    screenshot_url: str | None = None


class SsiEventBatchRequest(CamelModel):
    """Batch payload for ``POST /events/ssi/{scan_id}``."""

    events: list[SsiEventPayload]


class SsiEventResponse(CamelModel):
    """Serialised event row returned by ``GET /events/ssi/{scan_id}``."""

    id: str
    scan_id: str
    event_type: str
    timestamp: str
    data: dict[str, Any] = Field(default_factory=dict)
    screenshot_url: str | None = None


class SsiEventsListResponse(CamelModel):
    """Paginated event list for replay."""

    items: list[dict[str, Any]]
    count: int
    scan_id: str


# ---------------------------------------------------------------------------
# Redis helpers (optional — graceful degradation when Redis is absent)
# ---------------------------------------------------------------------------


def _get_redis_client() -> Any | None:
    """Return an aioredis client if Redis is configured, else None.

    Returns:
        An ``aioredis.Redis`` client or ``None`` when the ``redis.url``
        setting is empty.
    """
    settings = get_settings()
    url = settings.redis.url
    if not url:
        return None
    try:
        import redis.asyncio as aioredis  # type: ignore[import-untyped]

        return aioredis.from_url(url, decode_responses=True)
    except ImportError:
        logger.warning("redis package not installed — Redis pub/sub unavailable. Install via: pip install redis")
        return None
    except Exception as exc:
        logger.warning("Failed to create Redis client (%s) — falling back to DB polling", exc)
        return None


def _redis_channel(scan_id: str) -> str:
    """Return the Redis pub/sub channel name for a scan.

    Args:
        scan_id: The scan identifier.

    Returns:
        Channel string in the form ``ssi:events:{scan_id}``.
    """
    prefix = get_settings().redis.channel_prefix
    return f"{prefix}:{scan_id}"


async def _publish_events(scan_id: str, events: list[dict[str, Any]]) -> None:
    """Publish a batch of events to the Redis pub/sub channel.

    No-op when Redis is not configured.  Exceptions are logged but not
    propagated so ingestion never fails due to a Redis outage.

    Args:
        scan_id: The scan identifier.
        events: Serialised event dicts ready for JSON encoding.
    """
    client = _get_redis_client()
    if client is None:
        return
    try:
        channel = _redis_channel(scan_id)
        async with client:
            pipe = client.pipeline()
            for ev in events:
                pipe.publish(channel, json.dumps(ev, default=str))
            await pipe.execute()
    except Exception as exc:
        logger.warning("Redis publish failed for scan %s: %s", scan_id, exc)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/{scan_id}",
    summary="Ingest SSI investigation event batch",
    status_code=202,
    dependencies=[Depends(require_token)],
)
async def ingest_ssi_events(
    scan_id: str,
    body: SsiEventBatchRequest,
) -> dict[str, Any]:
    """Accept a batch of investigation events from the SSI service.

    Stores events in ``ssi_events`` and publishes them to Redis for
    immediate SSE fan-out.

    Args:
        scan_id: The scan / investigation ID.
        body: Event batch payload.

    Returns:
        Summary dict with ``inserted`` count and ``scan_id``.
    """
    if not body.events:
        return {"inserted": 0, "scan_id": scan_id}

    store = build_ssi_events_store()
    raw_events = [
        {
            "scan_id": scan_id,
            "event_type": ev.event_type,
            "timestamp": ev.timestamp,
            "data_json": ev.data,
            "screenshot_url": ev.screenshot_url,
        }
        for ev in body.events
    ]

    try:
        ids = store.insert_event_batch(raw_events)
    except Exception as exc:
        logger.error("Failed to insert SSI event batch for scan %s: %s", scan_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to persist events") from exc

    # Build serialisable event dicts for Redis publish.
    redis_events: list[dict[str, Any]] = [
        {
            "id": event_id,
            "scan_id": scan_id,
            "event_type": ev.event_type,
            "timestamp": ev.timestamp or datetime.now(timezone.utc).isoformat(),
            "data": ev.data,
            "screenshot_url": ev.screenshot_url,
        }
        for event_id, ev in zip(ids, body.events)
    ]
    await _publish_events(scan_id, redis_events)

    logger.info("Ingested %d events for scan %s", len(ids), scan_id)
    return {"inserted": len(ids), "scan_id": scan_id}


@router.get(
    "/{scan_id}",
    summary="Get all stored events for a scan (replay)",
    response_model=SsiEventsListResponse,
    dependencies=[Depends(require_token)],
)
def get_ssi_events(
    scan_id: str,
    limit: int = 1000,
    after: str | None = None,
) -> dict[str, Any]:
    """Return all stored events for a scan in chronological order.

    Used by the investigation detail page to replay an investigation for
    analysts who weren't watching the live feed, and by the Next.js SSE
    polling proxy for incremental event delivery.

    Args:
        scan_id: The scan / investigation ID.
        limit: Maximum number of events to return (default 1000).
        after: ISO-8601 timestamp.  When provided, only events with a
            timestamp strictly after this value are returned (used for
            incremental polling by the SSE proxy).

    Returns:
        ``SsiEventsListResponse`` with matching events.
    """
    after_ts: datetime | None = None
    if after:
        try:
            after_ts = datetime.fromisoformat(after.replace("Z", "+00:00"))
        except ValueError:
            pass
    store = build_ssi_events_store()
    events = store.get_events(scan_id, after_timestamp=after_ts, limit=limit)
    # Rename data_json → data for the wire format.
    for ev in events:
        if "data_json" in ev:
            ev["data"] = ev.pop("data_json")
    return {"items": events, "count": len(events), "scan_id": scan_id}


@router.get(
    "/{scan_id}/stream",
    summary="SSE stream of live investigation events",
    dependencies=[Depends(require_token)],
)
async def stream_ssi_events(
    scan_id: str,
    request: Request,
) -> StreamingResponse:
    """Stream SSI investigation events via Server-Sent Events.

    Attempts to subscribe to a Redis pub/sub channel for the scan first.
    When Redis is unavailable, falls back to polling ``ssi_events`` every
    ``redis.poll_interval_seconds`` seconds.

    The response sends ``data:`` lines conforming to the EventSource protocol.
    Each line carries a JSON-encoded event.  A ``keepalive`` comment line is
    sent every 15 seconds to prevent proxy timeouts.

    Args:
        scan_id: The scan / investigation ID.
        request: FastAPI request (used to detect client disconnection).

    Returns:
        A ``text/event-stream`` streaming response.
    """
    settings = get_settings()
    poll_interval = settings.redis.poll_interval_seconds

    async def event_generator() -> AsyncIterator[str]:
        """Yield SSE-formatted event strings."""
        # Attempt Redis subscription.
        client = _get_redis_client()
        if client is not None:
            async for chunk in _stream_from_redis(scan_id, client, request, poll_interval):
                yield chunk
        else:
            async for chunk in _stream_from_db(scan_id, request, poll_interval):
                yield chunk

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


async def _stream_from_redis(
    scan_id: str,
    client: Any,
    request: Request,
    poll_interval: float,
) -> AsyncIterator[str]:
    """Subscribe to the Redis channel and yield SSE-formatted events.

    Falls back to DB polling if the Redis subscription fails after the
    initial connection.

    Args:
        scan_id: The scan ID to subscribe to.
        client: An ``aioredis.Redis`` client instance.
        request: FastAPI request for disconnect detection.
        poll_interval: Polling interval in seconds (used if Redis fails).
    """
    channel = _redis_channel(scan_id)
    keepalive_interval = 15.0
    last_keepalive = asyncio.get_event_loop().time()

    try:
        async with client:
            pubsub = client.pubsub()
            await pubsub.subscribe(channel)
            logger.info("SSE: subscribed to Redis channel %s", channel)

            # Send initial replay of existing events before switching to live feed.
            store = build_ssi_events_store()
            existing = store.get_events(scan_id, limit=500)
            for ev in existing:
                if "data_json" in ev:
                    ev["data"] = ev.pop("data_json")
                yield f"data: {json.dumps(ev, default=str)}\n\n"

            while True:
                if await request.is_disconnected():
                    logger.debug("SSE: client disconnected from scan %s", scan_id)
                    break

                now = asyncio.get_event_loop().time()
                if now - last_keepalive >= keepalive_interval:
                    yield ": keepalive\n\n"
                    last_keepalive = now

                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
                if msg and msg.get("type") == "message":
                    try:
                        event_data = msg["data"]
                        # Validate it's parseable JSON (may already be a dict).
                        if isinstance(event_data, str):
                            json.loads(event_data)
                        yield f"data: {event_data}\n\n"
                    except (json.JSONDecodeError, KeyError):
                        pass

                await asyncio.sleep(0.05)

    except Exception as exc:
        logger.warning("Redis SSE stream failed for scan %s, falling back to DB: %s", scan_id, exc)
        async for chunk in _stream_from_db(scan_id, request, poll_interval):
            yield chunk


async def _stream_from_db(
    scan_id: str,
    request: Request,
    poll_interval: float,
) -> AsyncIterator[str]:
    """Poll ``ssi_events`` and yield SSE-formatted events.

    Streams all existing events first (replay), then polls incrementally for
    new rows at ``poll_interval``-second intervals.

    Args:
        scan_id: The scan ID to stream events for.
        request: FastAPI request for disconnect detection.
        poll_interval: Interval in seconds between DB polls.
    """
    store = build_ssi_events_store()
    keepalive_interval = 15.0
    last_keepalive = asyncio.get_event_loop().time()
    after_ts: datetime | None = None

    # Initial replay of existing events.
    existing = store.get_events(scan_id, limit=500)
    for ev in existing:
        if "data_json" in ev:
            ev["data"] = ev.pop("data_json")
        yield f"data: {json.dumps(ev, default=str)}\n\n"
    if existing:
        last_ts_str = existing[-1].get("timestamp")
        if last_ts_str:
            try:
                after_ts = datetime.fromisoformat(last_ts_str.replace("Z", "+00:00"))
            except ValueError:
                pass

    logger.info("SSE: polling DB for scan %s every %.1fs", scan_id, poll_interval)

    while True:
        if await request.is_disconnected():
            logger.debug("SSE: client disconnected from scan %s (DB poll)", scan_id)
            break

        await asyncio.sleep(poll_interval)

        now = asyncio.get_event_loop().time()
        if now - last_keepalive >= keepalive_interval:
            yield ": keepalive\n\n"
            last_keepalive = now

        new_events = store.get_events(scan_id, after_timestamp=after_ts, limit=100)
        for ev in new_events:
            if "data_json" in ev:
                ev["data"] = ev.pop("data_json")
            yield f"data: {json.dumps(ev, default=str)}\n\n"
        if new_events:
            last_ts_str = new_events[-1].get("timestamp")
            if last_ts_str:
                try:
                    after_ts = datetime.fromisoformat(last_ts_str.replace("Z", "+00:00"))
                except ValueError:
                    pass
