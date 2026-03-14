"""SSI re-scan job for takedown verification.

Periodically checks known scam URLs (from entities with type ``url``)
to verify whether sites have been taken down.  When a site is confirmed
unreachable, sets ``taken_down_at`` on the corresponding entity stat.

Run manually::

    i4g jobs takedown-check

Configure via ``I4G_ENRICHMENT__TAKEDOWN_CHECK_INTERVAL_HOURS``.
"""

from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime

import httpx
import sqlalchemy as sa
from sqlalchemy.orm import Session

from i4g.store.sql import entity_stats
from i4g.store.sql import session_factory as build_sql_session_factory
from i4g.worker.logging import configure_job_logging

logger = logging.getLogger(__name__)

_TIMEOUT = 10.0
_MAX_URLS_PER_RUN = 200

# HTTP status codes or connection failures that indicate takedown
_TAKEDOWN_STATUSES = frozenset({404, 410, 451, 502, 503, 521, 523})


def run_takedown_check(*, max_urls: int = _MAX_URLS_PER_RUN) -> dict[str, int]:
    """Check known scam URLs for takedown status.

    Fetches URL entities that have not been marked as taken down,
    attempts an HTTP HEAD request, and marks unreachable URLs.

    Args:
        max_urls: Maximum URLs to check per run.

    Returns:
        Dict with ``checked``, ``taken_down``, and ``errors`` counts.
    """
    sf = build_sql_session_factory()
    session: Session = sf()
    try:
        return _check_urls(session, max_urls)
    finally:
        session.close()


def _check_urls(session: Session, max_urls: int) -> dict[str, int]:
    """Perform the URL availability checks.

    Args:
        session: Active database session.
        max_urls: Maximum number of URLs to check.

    Returns:
        Summary counts.
    """
    # Find URL entities without a taken_down_at timestamp
    stmt = (
        sa.select(
            entity_stats.c.entity_type,
            entity_stats.c.canonical_value,
        )
        .where(
            entity_stats.c.entity_type == "url",
            entity_stats.c.taken_down_at.is_(None),
        )
        .limit(max_urls)
    )
    rows = session.execute(stmt).fetchall()

    if not rows:
        logger.info("No URLs to check for takedown")
        return {"checked": 0, "taken_down": 0, "errors": 0}

    results = {"checked": 0, "taken_down": 0, "errors": 0}
    now = datetime.now(UTC)

    for row in rows:
        url = row.canonical_value
        results["checked"] += 1
        is_down = _is_url_down(url)

        if is_down is None:
            results["errors"] += 1
            continue

        if is_down:
            # Update entity_stats with taken_down_at
            session.execute(
                entity_stats.update()
                .where(
                    entity_stats.c.entity_type == "url",
                    entity_stats.c.canonical_value == url,
                )
                .values(taken_down_at=now)
            )
            results["taken_down"] += 1
            logger.info("URL confirmed taken down: %s", url)

    session.commit()
    logger.info(
        "Takedown check: %d checked, %d confirmed down, %d errors",
        results["checked"],
        results["taken_down"],
        results["errors"],
    )
    return results


def _is_url_down(url: str) -> bool | None:
    """Check if a URL is unreachable or serving a takedown page.

    Args:
        url: Full URL to check.

    Returns:
        ``True`` if the URL appears to be taken down,
        ``False`` if it is still live,
        ``None`` if the check could not be completed.
    """
    # Ensure URL has a scheme
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    try:
        # verify=False: scam sites routinely use invalid/self-signed certificates
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True, verify=False) as client:  # noqa: S501
            resp = client.head(url)
            return resp.status_code in _TAKEDOWN_STATUSES
    except httpx.ConnectError:
        # Connection refused or DNS failure — likely taken down
        return True
    except httpx.TimeoutException:
        # Timeout — might be rate-limited; don't assume takedown
        return None
    except httpx.TransportError:
        # Other transport errors — inconclusive
        return None


def main() -> int:
    """Entry point for the takedown check job."""
    configure_job_logging()
    logger.info("Starting takedown verification check")
    try:
        results = run_takedown_check()
        logger.info("Takedown check finished: %s", results)
        return 0
    except Exception:
        logger.exception("Takedown check failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
