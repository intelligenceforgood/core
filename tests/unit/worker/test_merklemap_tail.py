"""Unit tests for ``i4g.worker.jobs.merklemap_tail``."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from i4g.clients.merklemap import DomainDiscovery
from i4g.worker.jobs import merklemap_tail


def _make_event(domain: str, first_seen_unix: int = 1717000000) -> DomainDiscovery:
    return DomainDiscovery(
        domain=domain,
        first_seen_unix=first_seen_unix,
        cert_issuer="Test CA",
        source_provenance={
            "source": "merklemap.tail",
            "commit_sha": "550cb04aa633c000724c339ada085c59444d5b78",
            "record_id": "deadbeef",
            "ingested_at": "2026-04-24T00:00:00Z",
            "ingest_job": "i4g.worker.jobs.merklemap_tail",
        },
    )


@pytest.fixture(autouse=True)
def _clear_settings_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Isolate each test from ambient env + cached settings."""
    monkeypatch.delenv("I4G_SETTINGS_FILE", raising=False)
    from i4g.settings import config as _config

    monkeypatch.setattr(_config, "LOCAL_CONFIG_FILE", tmp_path / "settings.local.toml")
    for var in (
        "I4G_PHISHDESTROY__MERKLEMAP_TAIL__ENABLED",
        "I4G_PHISHDESTROY__MERKLEMAP_TAIL__API_KEY",
        "PHISHDESTROY__MERKLEMAP_TAIL__ENABLED",
        "PHISHDESTROY__MERKLEMAP_TAIL__API_KEY",
        "PHISHDESTROY_MERKLEMAP_TAIL_ENABLED",
        "PHISHDESTROY_MERKLEMAP_TAIL_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    # Reload cached settings
    _config.reload_settings(env="local")


def _install_async_iter(monkeypatch: pytest.MonkeyPatch, events: list[DomainDiscovery]) -> None:
    async def _fake_tail(**_kwargs: Any) -> AsyncIterator[DomainDiscovery]:
        for e in events:
            yield e

    monkeypatch.setattr(merklemap_tail, "tail", _fake_tail)


def _build_in_memory_store(tmp_path: Path):
    from i4g.store.domain_discovery_store import DomainDiscoveryStore

    return DomainDiscoveryStore(db_path=tmp_path / "discoveries.db")


def test_main_returns_0_when_disabled(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    # Default is disabled; do not set anything.
    tail_calls = {"n": 0}

    async def _fake_tail(**_kwargs: Any):  # pragma: no cover - must not run
        tail_calls["n"] += 1
        if False:
            yield None  # type: ignore[unreachable]

    monkeypatch.setattr(merklemap_tail, "tail", _fake_tail)

    with caplog.at_level(logging.INFO, logger="i4g.worker.jobs.merklemap_tail"):
        code = merklemap_tail.main()

    assert code == 0
    assert tail_calls["n"] == 0
    assert any("merklemap-tail disabled" in r.message for r in caplog.records)


def test_main_returns_2_when_api_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("I4G_PHISHDESTROY__MERKLEMAP_TAIL__ENABLED", "true")
    from i4g.settings import config as _config

    _config.reload_settings(env="local")

    tail_calls = {"n": 0}

    async def _fake_tail(**_kwargs: Any):  # pragma: no cover
        tail_calls["n"] += 1
        if False:
            yield None  # type: ignore[unreachable]

    monkeypatch.setattr(merklemap_tail, "tail", _fake_tail)

    code = merklemap_tail.main()
    assert code == 2
    assert tail_calls["n"] == 0


def _enable_with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("I4G_PHISHDESTROY__MERKLEMAP_TAIL__ENABLED", "true")
    monkeypatch.setenv("I4G_PHISHDESTROY__MERKLEMAP_TAIL__API_KEY", "test-key")
    from i4g.settings import config as _config

    _config.reload_settings(env="local")


def test_filter_match_inserts_and_enqueues(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _enable_with_key(monkeypatch)
    store = _build_in_memory_store(tmp_path)
    monkeypatch.setattr(merklemap_tail, "build_domain_discovery_store", lambda: store)

    _install_async_iter(
        monkeypatch,
        [
            _make_event("trustwallet-secure.example"),
            _make_event("random-unrelated.example"),
        ],
    )

    trigger_calls: list[dict[str, Any]] = []

    def _fake_trigger(*, url: str, discovery_id: str, store: Any) -> str | None:
        trigger_calls.append({"url": url, "discovery_id": discovery_id})
        return "scan-uuid-1"

    monkeypatch.setattr(merklemap_tail, "enqueue_passive_scan_for_domain", _fake_trigger)

    mark_calls: list[tuple[str, str]] = []
    orig_mark = store.mark_enqueued

    def _spy_mark(discovery_id: str, scan_id: str):
        mark_calls.append((discovery_id, scan_id))
        return orig_mark(discovery_id, scan_id)

    monkeypatch.setattr(store, "mark_enqueued", _spy_mark)

    code = merklemap_tail.main()
    assert code == 0
    # Both events inserted
    assert len(store.list_recent_matches(limit=10)) == 1  # only the matching one is a match
    assert len(trigger_calls) == 1
    assert trigger_calls[0]["url"] == "trustwallet-secure.example"
    assert mark_calls == [(mark_calls[0][0], "scan-uuid-1")]


def test_filter_no_match_inserts_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _enable_with_key(monkeypatch)
    store = _build_in_memory_store(tmp_path)
    monkeypatch.setattr(merklemap_tail, "build_domain_discovery_store", lambda: store)

    _install_async_iter(monkeypatch, [_make_event("random-unrelated.example")])

    def _fail_trigger(**_kwargs: Any) -> str | None:
        raise AssertionError("enqueue_passive_scan_for_domain must not be called for non-matches")

    monkeypatch.setattr(merklemap_tail, "enqueue_passive_scan_for_domain", _fail_trigger)

    mark_calls: list[Any] = []
    monkeypatch.setattr(store, "mark_enqueued", lambda *a, **k: mark_calls.append((a, k)))

    code = merklemap_tail.main()
    assert code == 0
    assert mark_calls == []
    # One discovery inserted, not a match
    assert store.list_recent_matches(limit=10) == []


def test_scan_trigger_failure_does_not_crash_loop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _enable_with_key(monkeypatch)
    store = _build_in_memory_store(tmp_path)
    monkeypatch.setattr(merklemap_tail, "build_domain_discovery_store", lambda: store)

    _install_async_iter(
        monkeypatch,
        [
            _make_event("trustwallet-a.example"),
            _make_event("trustwallet-b.example"),
        ],
    )

    monkeypatch.setattr(
        merklemap_tail,
        "enqueue_passive_scan_for_domain",
        lambda **kwargs: None,
    )

    with caplog.at_level(logging.INFO, logger="i4g.worker.jobs.merklemap_tail"):
        code = merklemap_tail.main()

    assert code == 0
    # Both events processed, both matched, both trigger failures.
    matches = store.list_recent_matches(limit=10)
    assert len(matches) == 2
    assert all(m["enqueued_scan_id"] is None for m in matches)
    # Counter line should report scan_failures=2
    assert any("scan_failures=2" in r.message for r in caplog.records)


def test_max_events_terminates_loop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _enable_with_key(monkeypatch)
    store = _build_in_memory_store(tmp_path)
    monkeypatch.setattr(merklemap_tail, "build_domain_discovery_store", lambda: store)

    insert_calls = {"n": 0}
    orig_insert = store.insert

    def _spy_insert(**kwargs: Any):
        insert_calls["n"] += 1
        return orig_insert(**kwargs)

    monkeypatch.setattr(store, "insert", _spy_insert)

    _install_async_iter(
        monkeypatch,
        [_make_event(f"d{i}.example", first_seen_unix=1717000000 + i) for i in range(5)],
    )
    monkeypatch.setattr(merklemap_tail, "enqueue_passive_scan_for_domain", lambda **kwargs: None)

    code = merklemap_tail.main(max_events=2)
    assert code == 0
    assert insert_calls["n"] == 2
