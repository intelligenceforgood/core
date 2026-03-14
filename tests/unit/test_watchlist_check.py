"""Unit tests for watchlist notification job helper functions (S5-28 supplement)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from i4g.worker.jobs.watchlist_check import _parse_stored_count, run_watchlist_check


def test_parse_stored_count_with_baseline() -> None:
    """Extracts count from note with [baseline:N] tag."""
    assert _parse_stored_count("Some note [baseline:5]") == 5
    assert _parse_stored_count("[baseline:0]") == 0
    assert _parse_stored_count("text before [baseline:42] text after") == 42


def test_parse_stored_count_no_baseline() -> None:
    """Returns None when no baseline tag present."""
    assert _parse_stored_count("Just a regular note") is None
    assert _parse_stored_count("") is None
    assert _parse_stored_count(None) is None


# ---------------------------------------------------------------------------
# Watchlist resilience (S6-H10)
# ---------------------------------------------------------------------------


def test_single_item_failure_does_not_abort_remaining() -> None:
    """A failure processing one watchlist item does not prevent others from being processed."""
    good_item = {
        "watchlist_id": "good-1",
        "entity_type": "bank_account",
        "canonical_value": "1234",
        "alert_on_new_case": True,
        "alert_on_loss_increase": False,
        "note": "[baseline:1]",
    }
    bad_item = {
        "watchlist_id": "bad-1",
        "entity_type": "crypto_wallet",
        "canonical_value": "0xBAD",
        "alert_on_new_case": True,
        "alert_on_loss_increase": False,
        "note": "[baseline:0]",
    }

    mock_watchlist = MagicMock()
    mock_watchlist.list_items.return_value = [bad_item, good_item]

    mock_analytics = MagicMock()

    def _list_entity_stats(entity_type: str, limit: int = 1) -> list[dict]:
        if entity_type == "crypto_wallet":
            raise RuntimeError("Simulated API failure")
        return [{"canonical_value": "1234", "case_count": 3, "loss_sum": 100.0}]

    mock_analytics.list_entity_stats.side_effect = _list_entity_stats

    with (
        patch("i4g.services.factories.build_watchlist_store", return_value=mock_watchlist),
        patch("i4g.services.factories.build_analytics_store", return_value=mock_analytics),
    ):
        alerts = run_watchlist_check()

    # The good item should have been processed (new cases: 3 > baseline 1)
    assert mock_watchlist.create_alert.call_count == 1
    call_kwargs = mock_watchlist.create_alert.call_args[1]
    assert call_kwargs["watchlist_id"] == "good-1"
    assert call_kwargs["alert_type"] == "new_case"
    assert alerts == 1
