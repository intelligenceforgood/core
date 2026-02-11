"""Unit tests for i4g.utils.datetime_parse."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from i4g.utils.datetime_parse import parse_datetime


class TestParseDatetime:
    """Tests for parse_datetime with different input types and error modes."""

    # ── datetime inputs ──────────────────────────────────────────

    def test_aware_datetime_returned_as_is(self) -> None:
        dt = datetime(2024, 6, 15, 12, 0, tzinfo=timezone.utc)
        assert parse_datetime(dt) is dt

    def test_naive_datetime_gets_utc(self) -> None:
        dt = datetime(2024, 6, 15, 12, 0)
        result = parse_datetime(dt)
        assert result is not None
        assert result.tzinfo == timezone.utc
        assert result.replace(tzinfo=None) == dt

    # ── string inputs ────────────────────────────────────────────

    def test_iso_string(self) -> None:
        result = parse_datetime("2024-06-15T12:00:00+00:00")
        assert result is not None
        assert result == datetime(2024, 6, 15, 12, 0, tzinfo=timezone.utc)

    def test_z_suffix_normalised(self) -> None:
        result = parse_datetime("2024-06-15T12:00:00Z")
        assert result is not None
        assert result == datetime(2024, 6, 15, 12, 0, tzinfo=timezone.utc)

    def test_naive_iso_string_gets_utc(self) -> None:
        result = parse_datetime("2024-06-15T12:00:00")
        assert result is not None
        assert result.tzinfo == timezone.utc

    def test_empty_string_returns_none(self) -> None:
        assert parse_datetime("") is None

    def test_whitespace_string_returns_none(self) -> None:
        assert parse_datetime("   ") is None

    def test_invalid_string_returns_none(self) -> None:
        assert parse_datetime("not-a-date") is None

    # ── non-string / non-datetime inputs ─────────────────────────

    def test_none_returns_none(self) -> None:
        assert parse_datetime(None) is None

    def test_integer_returns_none(self) -> None:
        assert parse_datetime(12345) is None

    # ── on_error="now" ───────────────────────────────────────────

    def test_on_error_now_returns_current_time(self) -> None:
        before = datetime.now(timezone.utc)
        result = parse_datetime("bad", on_error="now")
        after = datetime.now(timezone.utc)
        assert before <= result <= after

    def test_on_error_now_with_none_input(self) -> None:
        result = parse_datetime(None, on_error="now")
        assert isinstance(result, datetime)
        assert result.tzinfo is not None

    # ── on_error="raise" ─────────────────────────────────────────

    def test_on_error_raise_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Cannot parse datetime"):
            parse_datetime("garbage", on_error="raise")

    def test_on_error_raise_with_none(self) -> None:
        with pytest.raises(ValueError, match="Cannot parse datetime"):
            parse_datetime(None, on_error="raise")
