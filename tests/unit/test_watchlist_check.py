"""Unit tests for watchlist notification job helper functions (S5-28 supplement)."""

from __future__ import annotations

from i4g.worker.jobs.watchlist_check import _parse_stored_count


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
