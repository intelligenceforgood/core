"""PhishDestroy merklemap SSE tail client (core port).

Streams live domain discoveries from the Merklemap API using Server-Sent Events
(SSE) over httpx async streaming. Reconnects on stream drop with exponential
back-off capped at 30 seconds.

This module is a **port** of ``ssi/src/ssi/osint/merklemap_client.py`` rather
than an import: ``core`` must not depend on ``ssi``. The SSE primitives
(parsing, record-id hashing, reconnect loop) are duplicated intentionally.

Gating model: callers (the ``merklemap_tail`` worker) gate on
``settings.phishdestroy.merklemap_tail.enabled`` and on a non-empty API key.
This module has no ``ProviderGate`` dependency.

See:
    * Provenance §2/§4 —
      ``copilot/.github/shared/phishdestroy-provenance.instructions.md``
      (``source = "merklemap.tail"``; ``commit_sha`` pinned to the
      merklemap-cli SHA below).
    * Reference implementation — ``ssi/src/ssi/osint/merklemap_client.py``.

Upstream SSE path confirmed from merklemap-cli @
``550cb04aa633c000724c339ada085c59444d5b78``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

logger = logging.getLogger(__name__)

# Confirmed from merklemap-cli/src/lib.rs tail() @ 550cb04aa633c000724c339ada085c59444d5b78.
_DEFAULT_STREAM_URL = "https://api.merklemap.com/live-domains?no_throttle=true"
_RECONNECT_CAP_SECONDS = 30
_INGEST_JOB = "i4g.worker.jobs.merklemap_tail"
_COMMIT_SHA = "550cb04aa633c000724c339ada085c59444d5b78"


@dataclass
class DomainDiscovery:
    """A single domain discovery emitted by the merklemap SSE stream."""

    domain: str
    first_seen_unix: int
    cert_issuer: str
    source_provenance: dict


# ── Internal helpers ──────────────────────────────────────────────────────────


def _record_id(domain: str, first_seen_unix: int) -> str:
    """Return deterministic record_id per provenance §2 for merklemap tail."""
    return hashlib.sha256(f"{domain}|{first_seen_unix}".encode()).hexdigest()


def _parse_sse_event(data: str, ingested_at: str) -> DomainDiscovery | None:
    """Parse a single SSE ``data:`` payload into a ``DomainDiscovery``.

    Returns ``None`` for progress events or malformed JSON.
    """
    try:
        obj = json.loads(data)
    except json.JSONDecodeError:
        return None

    # TailEntry shape from merklemap-cli: {"hostname": "..."}.
    # The stream may also carry {"progress_percentage": ...} progress events.
    hostname = obj.get("hostname") or obj.get("domain")
    if not hostname:
        return None

    # Merklemap live stream does not always include not_before; use current
    # epoch as a proxy so the record_id remains deterministic per event.
    first_seen_unix = obj.get("not_before") or int(datetime.now(UTC).timestamp())
    cert_issuer = obj.get("subject_common_name") or obj.get("issuer") or ""
    normalized_domain = str(hostname).strip().lower()
    normalized_first_seen = int(first_seen_unix)

    return DomainDiscovery(
        domain=normalized_domain,
        first_seen_unix=normalized_first_seen,
        cert_issuer=str(cert_issuer),
        source_provenance={
            "source": "merklemap.tail",
            "commit_sha": _COMMIT_SHA,
            "record_id": _record_id(normalized_domain, normalized_first_seen),
            "ingested_at": ingested_at,
            "ingest_job": _INGEST_JOB,
        },
    )


async def _stream_sse(
    url: str,
    api_key: str,
    http_client: httpx.AsyncClient,
) -> AsyncIterator[DomainDiscovery]:
    """Yield ``DomainDiscovery`` objects from a single SSE connection."""
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "text/event-stream"}
    buffer = ""

    async with http_client.stream("GET", url, headers=headers, timeout=None) as resp:
        resp.raise_for_status()
        async for chunk in resp.aiter_text():
            buffer += chunk
            while "\n\n" in buffer:
                event_block, buffer = buffer.split("\n\n", 1)
                for line in event_block.splitlines():
                    if line.startswith("data:"):
                        data = line[5:].strip()
                        ingested_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                        discovery = _parse_sse_event(data, ingested_at)
                        if discovery is not None:
                            yield discovery


# ── Public entry point ────────────────────────────────────────────────────────


async def tail(
    *,
    api_key: str,
    http_client: httpx.AsyncClient | None = None,
    url: str | None = None,
) -> AsyncIterator[DomainDiscovery]:
    """Yield live domain discoveries from the Merklemap SSE stream.

    Args:
        api_key: Merklemap API key (required; gating is the caller's
            responsibility).
        http_client: Injected async HTTP client (use ``httpx.MockTransport``
            in tests). When ``None``, a default ``httpx.AsyncClient`` is
            created and closed by this coroutine.
        url: Override the SSE URL (default: production live-domains feed).

    Yields:
        ``DomainDiscovery`` on each parsed event. Reconnects with exponential
        back-off (capped at ``_RECONNECT_CAP_SECONDS``) on stream errors.
    """
    stream_url = url or _DEFAULT_STREAM_URL
    own_client = http_client is None
    client = http_client or httpx.AsyncClient()

    reconnect_attempt = 0

    try:
        while True:
            try:
                async for discovery in _stream_sse(stream_url, api_key, client):
                    reconnect_attempt = 0  # reset on successful event
                    yield discovery
                # Stream ended cleanly — reconnect
                logger.info("merklemap SSE stream ended cleanly, reconnecting")
            except Exception as exc:
                reconnect_attempt += 1
                delay = min(2 ** (reconnect_attempt - 1), _RECONNECT_CAP_SECONDS)
                logger.warning(
                    "merklemap SSE stream error (attempt %d) — reconnecting in %.0fs: %s",
                    reconnect_attempt,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
    finally:
        if own_client:
            await client.aclose()
