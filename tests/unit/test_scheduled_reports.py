"""Unit tests for scheduled reports cadence computation (S5-31 supplement)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from i4g.worker.jobs.scheduled_reports import _compute_next_run


def test_weekly_cadence() -> None:
    """Weekly cadence advances by 7 days."""
    now = datetime(2025, 1, 1, tzinfo=UTC)
    result = _compute_next_run(now, "weekly")
    assert result == now + timedelta(weeks=1)


def test_monthly_cadence() -> None:
    """Monthly cadence advances by ~30 days."""
    now = datetime(2025, 1, 15, tzinfo=UTC)
    result = _compute_next_run(now, "monthly")
    assert result == now + timedelta(days=30)


def test_daily_cadence() -> None:
    """Daily cadence advances by 1 day."""
    now = datetime(2025, 6, 15, tzinfo=UTC)
    result = _compute_next_run(now, "daily")
    assert result == now + timedelta(days=1)


def test_unknown_cadence_defaults_weekly() -> None:
    """Unknown cadence defaults to weekly interval."""
    now = datetime(2025, 3, 1, tzinfo=UTC)
    result = _compute_next_run(now, "quarterly")
    assert result == now + timedelta(weeks=1)
