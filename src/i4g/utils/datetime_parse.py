"""Datetime parsing helpers.

Consolidates the ``_parse_datetime`` helper that was duplicated across
``reports/dossier_pilot.py``, ``reports/bundle_candidates.py``,
``api/review_search.py``, ``api/account_list.py``, and
``worker/jobs/account_list.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, overload


@overload
def parse_datetime(value: Any, *, on_error: Literal["none"]) -> datetime | None: ...
@overload
def parse_datetime(value: Any, *, on_error: Literal["now"]) -> datetime: ...
@overload
def parse_datetime(value: Any, *, on_error: Literal["raise"]) -> datetime: ...
@overload
def parse_datetime(value: Any) -> datetime | None: ...


def parse_datetime(value: Any, *, on_error: Literal["none", "now", "raise"] = "none") -> datetime | None:
    """Best-effort ISO-8601 datetime parser with configurable error handling.

    Accepts ``datetime`` objects, ISO-8601 strings (with or without trailing
    ``"Z"``), and ``None``. Naive datetimes are stamped with ``timezone.utc``.

    Args:
        value: A datetime, an ISO-8601 string, or ``None``.
        on_error: Strategy when *value* is unparseable:

            * ``"none"`` — return ``None`` (default).
            * ``"now"`` — return ``datetime.now(timezone.utc)``.
            * ``"raise"`` — raise ``ValueError``.

    Returns:
        A timezone-aware ``datetime``, or ``None`` per the *on_error* policy.

    Raises:
        ValueError: If *on_error* is ``"raise"`` and parsing fails.
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)

    if isinstance(value, str):
        text = value.strip()
        if text:
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            try:
                parsed = datetime.fromisoformat(text)
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            except ValueError:
                pass

    # Fallback
    if on_error == "now":
        return datetime.now(UTC)
    if on_error == "raise":
        raise ValueError(f"Cannot parse datetime from {value!r}")
    return None
