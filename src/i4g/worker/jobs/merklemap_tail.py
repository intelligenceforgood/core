"""Cloud Run / CLI entry point for the PhishDestroy merklemap SSE tail worker.

Consumes the Merklemap live-domain SSE stream, filters discoveries against a
brand-regex list, persists every event to ``domain_discoveries``, and on filter
match auto-enqueues a passive SSI scan via the same
``/trigger/investigate`` HTTP path used by ``auto_investigate``.

Gating model (no ``ProviderGate``): the worker returns early when
``settings.phishdestroy.merklemap_tail.enabled`` is ``False`` or the API key
is empty. This is appropriate for a long-running Cloud Run job whose lifecycle
is "the job exists or it doesn't".

See ``core/src/i4g/clients/merklemap.py`` for the SSE client primitives.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import signal
import sys
import time
import uuid
from datetime import UTC, datetime

from i4g.clients.merklemap import DomainDiscovery, tail
from i4g.services.factories import build_blocklist_hit_store, build_domain_discovery_store, build_ssi_store
from i4g.settings import get_settings
from i4g.store.blocklist_hit_store import BlocklistHitStore
from i4g.store.domain_discovery_store import DomainDiscoveryStore
from i4g.worker.logging import configure_job_logging


def levenshtein(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


LOGGER = logging.getLogger("i4g.worker.jobs.merklemap_tail")

_INGEST_JOB = "i4g.worker.jobs.merklemap_tail"


def enqueue_passive_scan_for_domain(
    *,
    url: str,
    discovery_id: str,
    store: DomainDiscoveryStore,
) -> str | None:
    """Trigger a passive SSI investigation for a tail-discovered domain.

    Mirrors ``auto_investigate._trigger_investigation`` but with
    ``scan_type="passive"`` and no ``case_investigations`` linkage — tail
    discoveries have no originating case. Settings are resolved internally
    via ``get_settings()`` so callers (router, worker) need not thread them.

    Args:
        url: Domain (or URL) discovered by the tail stream.
        discovery_id: ``domain_discoveries.discovery_id`` for log correlation.
        store: DomainDiscoveryStore (unused here — retained for symmetry and
            future audit hooks; caller invokes ``mark_enqueued`` on success).

    Returns:
        The ``scan_id`` on HTTP 2xx, ``None`` on any failure.
    """
    del store  # reserved for future audit hooks; see docstring.

    import httpx

    settings = get_settings()
    scan_id = str(uuid.uuid4())
    ssi_cfg = settings.ssi
    service_url = ssi_cfg.service_url

    try:
        from urllib.parse import urlparse as _urlparse

        domain = _urlparse(url if "://" in url else f"https://{url}").netloc
        if domain.startswith("www."):
            domain = domain[4:]
    except Exception:
        domain = None

    # Pre-create the scan row so downstream consumers can correlate
    # before the SSI service responds. Match auto_investigate's pattern.
    try:
        ssi_store = build_ssi_store()
        ssi_store.create_scan(
            scan_id=scan_id,
            url=url,
            scan_type="passive",
            domain=domain,
        )
    except Exception as exc:  # pragma: no cover - defensive
        LOGGER.warning(
            "Failed to pre-create scan row for %s (discovery=%s): %s",
            url,
            discovery_id,
            exc,
        )

    endpoint = f"{service_url.rstrip('/')}/trigger/investigate"
    payload = {
        "url": url,
        "scan_type": "passive",
        "scan_id": scan_id,
        "push_to_core": True,
        "dataset": "ssi",
    }

    headers: dict[str, str] = {}
    try:
        import google.auth.transport.requests
        import google.oauth2.id_token

        auth_request = google.auth.transport.requests.Request()
        token = google.oauth2.id_token.fetch_id_token(auth_request, audience=service_url)
        headers["Authorization"] = f"Bearer {token}"
    except Exception as exc:
        LOGGER.warning("Could not acquire OIDC token (will attempt without): %s", exc)

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(endpoint, json=payload, headers=headers)
            response.raise_for_status()
    except Exception as exc:
        LOGGER.warning(
            "Failed to trigger SSI service for %s (discovery=%s): %s",
            url,
            discovery_id,
            exc,
        )
        return None

    LOGGER.info(
        "merklemap-tail triggered SSI passive scan: url=%s scan_id=%s discovery_id=%s",
        url,
        scan_id,
        discovery_id,
    )
    return scan_id


async def _run(
    *,
    max_runtime_seconds: int | None,
    max_events: int | None,
) -> int:
    """Async tail loop. Returns the job's exit code."""
    settings = get_settings()
    configure_job_logging(settings)

    cfg = settings.phishdestroy.merklemap_tail

    if not cfg.enabled:
        LOGGER.info("merklemap-tail disabled; exiting.")
        return 0
    if not cfg.api_key:
        LOGGER.error(
            "merklemap-tail enabled but api_key is empty — set " "PHISHDESTROY__MERKLEMAP_TAIL__API_KEY before running."
        )
        return 2

    brand_patterns = [re.compile(p, re.IGNORECASE) for p in cfg.brand_regexes]

    discovery_store = build_domain_discovery_store()
    blocklist_store = build_blocklist_hit_store()
    protected_brands = getattr(cfg, "protected_brands", [])
    typosquat_threshold = getattr(cfg, "typosquat_threshold", 2)

    events_total = 0
    matches_total = 0
    scans_enqueued_total = 0
    scan_failures_total = 0

    shutdown = asyncio.Event()

    def _sigterm_handler(*_: object) -> None:
        LOGGER.info("merklemap-tail received SIGTERM; shutting down gracefully.")
        shutdown.set()

    loop = asyncio.get_event_loop()
    with contextlib.suppress(NotImplementedError, RuntimeError):  # non-posix/test
        loop.add_signal_handler(signal.SIGTERM, _sigterm_handler)

    start_time = time.monotonic()
    last_flush = start_time

    def _log_counters(reason: str) -> None:
        elapsed_hours = max((time.monotonic() - start_time) / 3600.0, 0.0001)
        scans_per_hour = scans_enqueued_total / elapsed_hours
        fpr = (scan_failures_total / matches_total) if matches_total > 0 else 0.0
        LOGGER.info(
            "merklemap-tail counters (%s): events=%d matches=%d scans_enqueued=%d scan_failures=%d "
            "fpr=%.3f scans/hr=%.1f",
            reason,
            events_total,
            matches_total,
            scans_enqueued_total,
            scan_failures_total,
            fpr,
            scans_per_hour,
        )

    LOGGER.info(
        "merklemap-tail starting (brand_patterns=%d, batch_size=%d, flush_interval_seconds=%d)",
        len(brand_patterns),
        cfg.batch_size,
        cfg.flush_interval_seconds,
    )

    exit_code = 0
    try:
        async for event in tail(api_key=cfg.api_key):
            if shutdown.is_set():
                break
            if max_runtime_seconds is not None and (time.monotonic() - start_time) >= max_runtime_seconds:
                LOGGER.info("merklemap-tail reached max_runtime_seconds=%d", max_runtime_seconds)
                break

            is_match, enqueued_ok = _handle_event(
                event=event,
                brand_patterns=brand_patterns,
                protected_brands=protected_brands,
                typosquat_threshold=typosquat_threshold,
                discovery_store=discovery_store,
                blocklist_store=blocklist_store,
            )
            events_total += 1
            if is_match:
                matches_total += 1
                if enqueued_ok:
                    scans_enqueued_total += 1
                else:
                    scan_failures_total += 1

            now = time.monotonic()
            if now - last_flush >= max(1, cfg.flush_interval_seconds):
                _log_counters("flush")
                last_flush = now

            if max_events is not None and events_total >= max_events:
                LOGGER.info("merklemap-tail reached max_events=%d", max_events)
                break
    except Exception:  # pragma: no cover - defensive
        LOGGER.exception("merklemap-tail crashed unexpectedly")
        exit_code = 1
    finally:
        _log_counters("shutdown")

    return exit_code


def _handle_event(
    *,
    event: DomainDiscovery,
    brand_patterns: list[re.Pattern[str]],
    protected_brands: list[str],
    typosquat_threshold: int,
    discovery_store: DomainDiscoveryStore,
    blocklist_store: BlocklistHitStore,
) -> tuple[bool, bool]:
    """Insert one discovery row and, on brand match, trigger a passive SSI scan.

    Returns:
        Tuple of ``(is_match, enqueued_ok)``. ``enqueued_ok`` is ``False`` for
        non-matches and for matches whose trigger call returned ``None``.
    """
    domain = event.domain.lower()

    matched = [p for p in brand_patterns if p.search(domain)]

    # 1. Typosquat
    domain_parts = domain.split(".")
    base_name = domain_parts[0] if len(domain_parts) > 1 else domain
    if domain.startswith("www.") and len(domain_parts) > 2:
        base_name = domain_parts[1]

    is_typosquat = False
    for brand in protected_brands:
        if levenshtein(base_name, brand.lower()) <= typosquat_threshold:
            is_typosquat = True
            break

    # 2. Blocklist
    hits = blocklist_store.list_by_indicator(domain, limit=1)
    has_blocklist_hit = len(hits) > 0

    reasons = []
    if matched:
        reasons.append("brand-regex")
    if is_typosquat:
        reasons.append("typosquat")
    if has_blocklist_hit:
        reasons.append("blocklist")

    is_match = len(reasons) > 0
    filter_reason = "|".join(reasons)[:200] if is_match else None

    seen_at = datetime.fromtimestamp(event.first_seen_unix, tz=UTC)
    row = discovery_store.insert(
        domain=event.domain,
        source="merklemap.tail",
        seen_at=seen_at,
        subject_common_name=event.cert_issuer or None,
        filter_match=is_match,
        filter_reason=filter_reason,
        raw=None,
        source_provenance=event.source_provenance,
    )
    discovery_id = row["discovery_id"]

    if not is_match:
        return False, False

    scan_id = enqueue_passive_scan_for_domain(
        url=event.domain,
        discovery_id=discovery_id,
        store=discovery_store,
    )
    if scan_id is None:
        return True, False
    discovery_store.mark_enqueued(discovery_id, scan_id)
    return True, True


def main(
    *,
    max_runtime_seconds: int | None = None,
    max_events: int | None = None,
) -> int:
    """Entry point executed by the Cloud Run job container or CLI.

    Args:
        max_runtime_seconds: Stop after N seconds (default: run until SIGTERM).
        max_events: Stop after N events (default: unbounded).

    Returns:
        ``0`` on graceful shutdown, ``1`` on unhandled error,
        ``2`` on misconfiguration.
    """
    return asyncio.run(_run(max_runtime_seconds=max_runtime_seconds, max_events=max_events))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
