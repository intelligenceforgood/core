"""URL deduplication check for SSI investigations.

Before triggering a new SSI investigation, callers should use
``check_url_duplicate()`` to determine whether a recent scan already
covers the same URL (after normalization).  This prevents redundant
work and preserves Cloud Run budget.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from i4g.store import sql as sql_schema
from i4g.utils.url_normalization import normalize_url

logger = logging.getLogger(__name__)


@dataclass
class DedupResult:
    """Result of a URL dedup check."""

    is_duplicate: bool
    existing_scan_id: str | None = None
    existing_risk_score: float | None = None
    existing_completed_at: datetime | None = None
    days_since_scan: int | None = None
    reason: str = ""  # "fresh_scan_exists", "stale_scan", "scan_in_progress", "no_prior_scan"


def check_url_duplicate(
    url: str,
    *,
    session_factory: sessionmaker,
    staleness_days: int = 30,
) -> DedupResult:
    """Check if a URL has been recently investigated.

    Normalizes the URL and queries ``site_scans`` for an existing scan
    with a matching ``normalized_url``.  Scans that are still running or
    pending are treated as duplicates (the caller should wait).

    Args:
        url: Raw URL to check.
        session_factory: DB session factory.
        staleness_days: Window in days.  Scans older than this are
            considered stale and eligible for re-investigation.

    Returns:
        DedupResult with duplicate status and existing scan info.
    """
    normalized = normalize_url(url)

    stmt = (
        sa.select(
            sql_schema.site_scans.c.scan_id,
            sql_schema.site_scans.c.risk_score,
            sql_schema.site_scans.c.completed_at,
            sql_schema.site_scans.c.status,
        )
        .where(
            sql_schema.site_scans.c.normalized_url == normalized,
            sql_schema.site_scans.c.status.in_(["completed", "running", "pending"]),
        )
        .order_by(sql_schema.site_scans.c.completed_at.desc().nulls_last())
        .limit(1)
    )

    with session_factory() as session:
        row = session.execute(stmt).fetchone()

    if row is None:
        return DedupResult(is_duplicate=False, reason="no_prior_scan")

    scan_id = str(row.scan_id)
    risk_score = float(row.risk_score) if row.risk_score is not None else None
    completed_at = row.completed_at
    status = row.status

    # Running or pending — treat as duplicate (scan in progress).
    if status in ("running", "pending"):
        return DedupResult(
            is_duplicate=True,
            existing_scan_id=scan_id,
            existing_risk_score=risk_score,
            existing_completed_at=completed_at,
            reason="scan_in_progress",
        )

    # Completed scan — check staleness.
    if completed_at is not None:
        cutoff = datetime.now(UTC) - timedelta(days=staleness_days)
        # Ensure timezone-aware comparison
        completed_at_aware = completed_at.replace(tzinfo=UTC) if completed_at.tzinfo is None else completed_at
        days_since = (datetime.now(UTC) - completed_at_aware).days

        if completed_at_aware >= cutoff:
            return DedupResult(
                is_duplicate=True,
                existing_scan_id=scan_id,
                existing_risk_score=risk_score,
                existing_completed_at=completed_at,
                days_since_scan=days_since,
                reason="fresh_scan_exists",
            )
        return DedupResult(
            is_duplicate=False,
            existing_scan_id=scan_id,
            existing_risk_score=risk_score,
            existing_completed_at=completed_at,
            days_since_scan=days_since,
            reason="stale_scan",
        )

    # Completed but no completed_at timestamp — treat as stale.
    return DedupResult(
        is_duplicate=False,
        existing_scan_id=scan_id,
        existing_risk_score=risk_score,
        reason="stale_scan",
    )
