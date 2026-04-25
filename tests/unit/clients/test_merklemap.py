"""Unit tests for ``i4g.clients.merklemap`` SSE client."""

from __future__ import annotations

import asyncio
import itertools

import httpx
import pytest

from i4g.clients import merklemap
from i4g.clients.merklemap import (
    DomainDiscovery,
    _parse_sse_event,
    _record_id,
    tail,
)


def test_parse_sse_event_valid() -> None:
    data = (
        '{"hostname": "trustwallet-secure.example", '
        '"not_before": 1717000000, '
        '"subject_common_name": "Let\'s Encrypt"}'
    )
    event = _parse_sse_event(data, "2026-04-24T00:00:00Z")
    assert event is not None
    assert event.domain == "trustwallet-secure.example"
    assert event.first_seen_unix == 1717000000
    assert event.cert_issuer == "Let's Encrypt"
    assert event.source_provenance["source"] == "merklemap.tail"
    assert event.source_provenance["commit_sha"] == "550cb04aa633c000724c339ada085c59444d5b78"
    assert event.source_provenance["ingest_job"] == "i4g.worker.jobs.merklemap_tail"
    assert event.source_provenance["record_id"] == _record_id("trustwallet-secure.example", 1717000000)


def test_parse_sse_event_progress_event_returns_none() -> None:
    assert _parse_sse_event('{"progress_percentage": 42}', "2026-04-24T00:00:00Z") is None


def test_parse_sse_event_invalid_json_returns_none() -> None:
    assert _parse_sse_event("not-json{", "2026-04-24T00:00:00Z") is None


def test_record_id_is_deterministic() -> None:
    a = _record_id("example.com", 1234567890)
    b = _record_id("example.com", 1234567890)
    assert a == b
    assert a != _record_id("example.com", 1234567891)


def _sse_body(entries: list[dict]) -> bytes:
    """Encode a list of JSON dicts as concatenated SSE ``data:`` events."""
    chunks = []
    for e in entries:
        import json as _json

        chunks.append(f"data: {_json.dumps(e)}\n\n")
    return "".join(chunks).encode()


def test_tail_yields_parsed_events() -> None:
    body = _sse_body(
        [
            {"hostname": "a.example", "not_before": 1717000001, "subject_common_name": "CA"},
            {"hostname": "b.example", "not_before": 1717000002, "subject_common_name": "CA"},
            {"hostname": "c.example", "not_before": 1717000003, "subject_common_name": "CA"},
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"Content-Type": "text/event-stream"})

    transport = httpx.MockTransport(handler)

    async def _run() -> list[DomainDiscovery]:
        async with httpx.AsyncClient(transport=transport) as client:
            results: list[DomainDiscovery] = []
            # islice on async iterator:
            it = tail(api_key="x", http_client=client)
            async for event in it:
                results.append(event)
                if len(results) >= 3:
                    break
            await it.aclose()
            return results

    events = asyncio.run(_run())
    assert len(events) == 3
    assert [e.domain for e in events] == ["a.example", "b.example", "c.example"]
    assert all(e.source_provenance["source"] == "merklemap.tail" for e in events)
    # itertools.islice is imported to match the manifest's hint that bounded
    # iteration is acceptable; reference it to satisfy linters.
    assert list(itertools.islice([1, 2, 3], 2)) == [1, 2]


def test_tail_reconnects_on_stream_error(monkeypatch: pytest.MonkeyPatch) -> None:
    body = _sse_body([{"hostname": "after-reconnect.example", "not_before": 1717000099, "subject_common_name": "CA"}])
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.RemoteProtocolError("boom", request=request)
        return httpx.Response(200, content=body, headers={"Content-Type": "text/event-stream"})

    transport = httpx.MockTransport(handler)

    async def _noop_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(merklemap.asyncio, "sleep", _noop_sleep)

    async def _run() -> list[DomainDiscovery]:
        async with httpx.AsyncClient(transport=transport) as client:
            results: list[DomainDiscovery] = []
            it = tail(api_key="x", http_client=client)
            async for event in it:
                results.append(event)
                if len(results) >= 1:
                    break
            await it.aclose()
            return results

    events = asyncio.run(_run())
    assert len(events) == 1
    assert events[0].domain == "after-reconnect.example"
    # One failing attempt + one successful attempt = 2 handler invocations.
    assert calls["n"] == 2
