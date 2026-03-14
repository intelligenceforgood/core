"""Watchlist notification job — checks watched entities for new activity.

Queries entity stats for each watchlist item and generates alerts when:
- A new case references the watched entity (case count increased).
- Cumulative loss exceeds the configured threshold.

Run manually::

    i4g jobs watchlist-check

Or schedule via ``I4G_ANALYTICS__WATCHLIST_CHECK_INTERVAL_MINUTES``.
"""

from __future__ import annotations

import logging
import sys

from i4g.worker.logging import configure_job_logging

logger = logging.getLogger(__name__)


def run_watchlist_check() -> int:
    """Execute one pass of the watchlist notification check.

    Compares current entity stats against the last-known values stored
    in watchlist item metadata and generates alerts for changes.

    Returns:
        Number of alerts created.
    """
    from i4g.services.factories import build_analytics_store, build_watchlist_store

    watchlist = build_watchlist_store()
    analytics = build_analytics_store()

    items = watchlist.list_items(limit=10000)
    if not items:
        logger.info("No watchlist items — nothing to check")
        return 0

    alerts_created = 0

    for item in items:
        entity_type = item["entity_type"]
        canonical_value = item["canonical_value"]
        watchlist_id = item["watchlist_id"]

        # Fetch current stats for this entity
        stats_list = analytics.list_entity_stats(
            entity_type=entity_type,
            limit=1,
        )
        matching = [s for s in stats_list if s.get("canonical_value") == canonical_value]
        if not matching:
            continue

        stats = matching[0]
        current_case_count = int(stats.get("case_count", 0))
        current_loss = float(stats.get("loss_sum", 0.0))

        # Check for new case activity
        if item.get("alert_on_new_case"):
            # Compare with stored case count in note metadata (simple approach)
            # The first time we just record baseline — no alert
            stored_count = _parse_stored_count(item.get("note"))
            if stored_count is not None and current_case_count > stored_count:
                new_cases = current_case_count - stored_count
                msg = f"{entity_type}:{canonical_value} has {new_cases} " f"new case(s) (total: {current_case_count})"
                watchlist.create_alert(
                    watchlist_id=watchlist_id,
                    alert_type="new_case",
                    message=msg,
                    data={"previous_count": stored_count, "current_count": current_case_count},
                )
                alerts_created += 1

            # Update stored baseline
            _update_stored_count(watchlist, watchlist_id, current_case_count, item.get("note"))

        # Check for loss threshold breach
        if item.get("alert_on_loss_increase"):
            threshold = float(item.get("loss_threshold") or 0)
            if threshold > 0 and current_loss >= threshold:
                # Only alert once per threshold crossing — check existing alerts
                existing_alerts = watchlist.list_alerts(watchlist_id=watchlist_id, limit=100)
                already_alerted = any(
                    a.get("alert_type") == "loss_increase" and a.get("data", {}).get("threshold") == threshold
                    for a in existing_alerts
                )
                if not already_alerted:
                    watchlist.create_alert(
                        watchlist_id=watchlist_id,
                        alert_type="loss_increase",
                        message=(
                            f"{entity_type}:{canonical_value} cumulative loss "
                            f"${current_loss:,.2f} exceeds threshold ${threshold:,.2f}"
                        ),
                        data={"current_loss": current_loss, "threshold": threshold},
                    )
                    alerts_created += 1

    logger.info("Watchlist check complete: %d alert(s) created", alerts_created)
    return alerts_created


def _parse_stored_count(note: str | None) -> int | None:
    """Extract previously stored case count from the note field.

    The watchlist job appends ``[baseline:N]`` to the note field to track
    the last-known case count without requiring an additional column.

    Args:
        note: Current note text.

    Returns:
        Previously stored case count, or ``None`` if no baseline.
    """
    if not note:
        return None
    import re

    match = re.search(r"\[baseline:(\d+)\]", note)
    return int(match.group(1)) if match else None


def _update_stored_count(
    store: object,
    watchlist_id: str,
    case_count: int,
    current_note: str | None,
) -> None:
    """Update the stored baseline case count in the note field.

    Args:
        store: WatchlistStore instance.
        watchlist_id: Watchlist item ID.
        case_count: Current case count to store.
        current_note: Existing note text.
    """
    import re

    from i4g.store.watchlist_store import WatchlistStore

    if not isinstance(store, WatchlistStore):
        return

    base_note = current_note or ""
    # Remove any existing baseline tag
    base_note = re.sub(r"\s*\[baseline:\d+\]", "", base_note).strip()
    new_note = f"{base_note} [baseline:{case_count}]".strip()
    store.update_item(watchlist_id, note=new_note)


def main() -> int:
    """Entry point for the watchlist check job."""
    configure_job_logging()
    logger.info("Starting watchlist notification check")
    try:
        alerts = run_watchlist_check()
        logger.info("Watchlist check finished — %d alert(s)", alerts)
        return 0
    except Exception:
        logger.exception("Watchlist check failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
