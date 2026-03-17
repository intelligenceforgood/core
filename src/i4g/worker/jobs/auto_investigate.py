"""Auto-investigate URLs found in cases.

Queries cases with URL indicators that have not been investigated,
applies domain blocklist and dedup, then triggers SSI investigations
via the SSI Cloud Run Service.

Usage::

    i4g jobs auto-investigate [--dry-run] [--limit N]

The job is gated by the ``auto_investigate.enabled`` setting.  When
disabled, it exits immediately with code 0.
"""

from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from i4g.services.domain_filter import get_merged_blocklist, is_domain_blocked
from i4g.services.investigation_dedup import check_url_duplicate
from i4g.settings import get_settings
from i4g.store import sql as sql_schema
from i4g.store.sql import dialect_insert
from i4g.store.sql import session_factory as build_sql_session_factory
from i4g.task_status import TaskStatusReporter
from i4g.utils.url_normalization import normalize_url
from i4g.worker.logging import configure_job_logging

logger = logging.getLogger(__name__)


def _get_uninvestigated_urls(session: Session, *, limit: int = 100) -> list[dict[str, Any]]:
    """Query URL indicators not linked to any investigation.

    Returns a list of dicts with keys ``indicator_id``, ``case_id``,
    ``url``, ``case_dataset``.  Excludes cases with
    ``dataset='ssi'`` (already SSI-originated).

    Args:
        session: Active DB session.
        limit: Maximum number of results.

    Returns:
        List of URL indicator dicts.
    """
    # Subquery: case_ids that already have at least one investigation link
    investigated_cases = sa.select(sa.distinct(sql_schema.case_investigations.c.case_id))

    stmt = (
        sa.select(
            sql_schema.indicators.c.indicator_id,
            sql_schema.indicators.c.case_id,
            sql_schema.indicators.c.number.label("url"),
            sql_schema.cases.c.dataset.label("case_dataset"),
        )
        .select_from(
            sql_schema.indicators.join(
                sql_schema.cases,
                sql_schema.indicators.c.case_id == sql_schema.cases.c.case_id,
            )
        )
        .where(
            sql_schema.indicators.c.category == "url",
            sql_schema.indicators.c.type == "url",
            sql_schema.cases.c.dataset != "ssi",
            sql_schema.indicators.c.case_id.notin_(investigated_cases),
        )
        .limit(limit)
    )

    rows = session.execute(stmt).fetchall()
    return [
        {
            "indicator_id": str(row.indicator_id),
            "case_id": row.case_id,
            "url": row.url,
            "case_dataset": row.case_dataset,
        }
        for row in rows
    ]


def _deduplicate_urls(urls: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group URL dicts by normalized URL.

    Each normalized URL will trigger at most one investigation.
    The result maps ``normalized_url`` → list of indicator dicts that
    share that same normalized form.

    Args:
        urls: Flat list of URL indicator dicts.

    Returns:
        Dict mapping normalized URL to list of indicator dicts.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in urls:
        normalized = normalize_url(item["url"])
        groups.setdefault(normalized, []).append(item)
    return groups


def _trigger_investigation(
    url: str,
    case_ids: list[str],
    *,
    session: Session,
    settings: Any,
) -> str | None:
    """Trigger an SSI investigation for a URL and link to originating cases.

    Uses the SSI Cloud Run Service trigger (same mechanism as the API
    endpoint).  On success, inserts ``case_investigations`` rows for
    each originating ``case_id`` with ``trigger_type='auto'``.

    Args:
        url: URL to investigate.
        case_ids: Case IDs that reference this URL.
        session: Active DB session.
        settings: Application settings.

    Returns:
        The ``scan_id`` on success, ``None`` on failure.
    """
    import uuid

    import httpx

    scan_id = str(uuid.uuid4())
    ssi_cfg = settings.ssi
    service_url = ssi_cfg.service_url

    # Pre-create the scan row
    try:
        from urllib.parse import urlparse as _urlparse

        domain = _urlparse(url if "://" in url else f"https://{url}").netloc
        if domain.startswith("www."):
            domain = domain[4:]
    except Exception:
        domain = None

    try:
        from i4g.services.factories import build_ssi_store

        ssi_store = build_ssi_store()
        ssi_store.create_scan(
            scan_id=scan_id,
            url=url,
            scan_type="full",
            domain=domain,
        )
    except Exception as exc:
        logger.warning("Failed to pre-create scan row for %s: %s", url, exc)

    # Trigger the SSI Cloud Run Service
    endpoint = f"{service_url.rstrip('/')}/trigger/investigate"
    payload = {
        "url": url,
        "scan_type": "full",
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
        logger.warning("Could not acquire OIDC token (will attempt without): %s", exc)

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(endpoint, json=payload, headers=headers)
            response.raise_for_status()
    except Exception as exc:
        logger.error("Failed to trigger SSI service for %s: %s", url, exc)
        return None

    # Link the investigation to all originating cases
    for case_id in case_ids:
        try:
            ins = dialect_insert(session, sql_schema.case_investigations)
            ins_stmt = ins.on_conflict_do_nothing(index_elements=["case_id", "scan_id"])
            session.execute(
                ins_stmt.values(
                    case_id=case_id,
                    scan_id=scan_id,
                    trigger_type="auto",
                )
            )
        except Exception as exc:
            logger.warning("Failed to link scan %s to case %s: %s", scan_id, case_id, exc)

    session.commit()
    logger.info("Auto-investigation triggered: url=%s scan_id=%s cases=%s", url, scan_id, case_ids)
    return scan_id


def main(*, dry_run: bool = False, limit: int = 100) -> int:
    """Entry point for the auto-investigate worker job.

    Args:
        dry_run: When ``True``, report what would be triggered without
            actually triggering investigations.
        limit: Maximum number of URLs to process per run.

    Returns:
        0 on success, 1 if any failures occurred.
    """
    settings = get_settings()
    configure_job_logging(settings)
    reporter = TaskStatusReporter()

    if not settings.auto_investigate.enabled:
        logger.info("Auto-investigation disabled; exiting.")
        if reporter.is_enabled():
            reporter.update(status="finished", message="Auto-investigation is disabled")
        return 0

    logger.info("auto-investigate: starting (dry_run=%s, limit=%d)", dry_run, limit)
    if reporter.is_enabled():
        reporter.update(status="processing", message="Starting auto-investigation")

    sf = build_sql_session_factory()
    session: Session = sf()

    try:
        # 1. Query URL indicators not yet investigated
        url_indicators = _get_uninvestigated_urls(session, limit=limit)
        logger.info("auto-investigate: %d URL indicators found", len(url_indicators))

        if not url_indicators:
            if reporter.is_enabled():
                reporter.update(status="finished", message="No uninvestigated URLs found")
            return 0

        # 2. Group by normalized URL
        url_groups = _deduplicate_urls(url_indicators)
        logger.info("auto-investigate: %d unique URLs after dedup", len(url_groups))

        # 3. Filter through domain blocklist
        blocklist = get_merged_blocklist(settings.auto_investigate.domain_blocklist)
        staleness_days = settings.auto_investigate.staleness_days
        max_concurrent = settings.auto_investigate.max_concurrent

        triggered = 0
        skipped_blocklist = 0
        skipped_dedup = 0
        failures = 0
        total = len(url_groups)

        for idx, (_normalized_url, indicator_dicts) in enumerate(url_groups.items(), 1):
            raw_url = indicator_dicts[0]["url"]
            case_ids = list({d["case_id"] for d in indicator_dicts})

            # 3a. Domain blocklist check
            if is_domain_blocked(raw_url, blocklist):
                logger.debug("auto-investigate: blocked domain for %s", raw_url)
                skipped_blocklist += 1
                continue

            # 4. Dedup check against site_scans
            try:
                dedup = check_url_duplicate(raw_url, session_factory=sf, staleness_days=staleness_days)
                if dedup.is_duplicate:
                    logger.debug(
                        "auto-investigate: dedup skip for %s (%s)",
                        raw_url,
                        dedup.reason,
                    )
                    skipped_dedup += 1

                    # Still link existing scan to cases if not already linked
                    if dedup.existing_scan_id:
                        for case_id in case_ids:
                            try:
                                ins = dialect_insert(session, sql_schema.case_investigations)
                                ins_stmt = ins.on_conflict_do_nothing(index_elements=["case_id", "scan_id"])
                                session.execute(
                                    ins_stmt.values(
                                        case_id=case_id,
                                        scan_id=dedup.existing_scan_id,
                                        trigger_type="auto",
                                    )
                                )
                            except Exception:
                                pass
                        session.commit()
                    continue
            except Exception as exc:
                logger.warning("auto-investigate: dedup check failed for %s: %s", raw_url, exc)

            # 5. Trigger investigation (respect max_concurrent)
            if triggered >= max_concurrent:
                logger.info(
                    "auto-investigate: max_concurrent (%d) reached; stopping",
                    max_concurrent,
                )
                break

            if dry_run:
                logger.info(
                    "auto-investigate [DRY-RUN]: would trigger for %s (cases=%s)",
                    raw_url,
                    case_ids,
                )
                triggered += 1
            else:
                scan_id = _trigger_investigation(
                    raw_url,
                    case_ids,
                    session=session,
                    settings=settings,
                )
                if scan_id:
                    triggered += 1
                else:
                    failures += 1

            if reporter.is_enabled() and (idx % 5 == 0 or idx == total):
                reporter.update(
                    status="processing",
                    message=f"Processed {idx}/{total} URLs",
                    progress=idx,
                    total=total,
                    triggered=triggered,
                    skipped_dedup=skipped_dedup,
                    skipped_blocklist=skipped_blocklist,
                )

        prefix = "[DRY-RUN] " if dry_run else ""
        logger.info(
            "auto-investigate: %s%d triggered, %d skipped (dedup), %d skipped (blocklist), %d failures",
            prefix,
            triggered,
            skipped_dedup,
            skipped_blocklist,
            failures,
        )
        if reporter.is_enabled():
            reporter.update(
                status="finished",
                message=f"{prefix}Auto-investigation complete",
                triggered=triggered,
                skipped_dedup=skipped_dedup,
                skipped_blocklist=skipped_blocklist,
                failures=failures,
            )

        return 0 if failures == 0 else 1

    finally:
        session.close()
