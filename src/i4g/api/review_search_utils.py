"""Coercion and parsing helpers for review search payloads."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from i4g.utils.datetime_parse import parse_datetime


def coerce_string_list(*values: Any) -> list[str]:
    """Coerce one or more raw values into a deduplicated string list."""
    result: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            for item in value:
                text = clean_text_value(item)
                if text:
                    result.append(text)
        else:
            text = clean_text_value(value)
            if text:
                result.append(text)

    seen: set[str] = set()
    unique: list[str] = []
    for item in result:
        lowered = item.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        unique.append(item)
    return unique


def coerce_entities(raw: Any) -> list[dict[str, str]]:
    """Normalise raw entity filter input into a list of entity dicts."""
    if not raw:
        return []
    normalized: list[dict[str, str]] = []
    match_modes = {"exact", "prefix", "contains"}
    candidates = raw if isinstance(raw, list) else [raw]
    for entry in candidates:
        if isinstance(entry, dict):
            entity_type = clean_text_value(entry.get("type"))
            entity_value = clean_text_value(entry.get("value"))
            if not entity_type or not entity_value:
                continue
            match_mode = clean_text_value(entry.get("match_mode")) or "exact"
            if match_mode not in match_modes:
                match_mode = "exact"
            normalized.append({"type": entity_type, "value": entity_value, "match_mode": match_mode})
        elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
            entity_type = clean_text_value(entry[0])
            entity_value = clean_text_value(entry[1])
            if not entity_type or not entity_value:
                continue
            normalized.append({"type": entity_type, "value": entity_value, "match_mode": "exact"})
    return normalized


def coerce_time_range(raw: Any) -> dict[str, datetime] | None:
    """Parse a time-range dict with ``start``/``end`` (or ``from``/``to``)."""
    if not isinstance(raw, dict):
        return None
    start_value = raw.get("start") or raw.get("from")
    end_value = raw.get("end") or raw.get("to")
    if not start_value or not end_value:
        return None
    start_dt = parse_datetime_value(start_value)
    end_dt = parse_datetime_value(end_value)
    if not start_dt or not end_dt or end_dt < start_dt:
        return None
    return {"start": start_dt, "end": end_dt}


def parse_datetime_value(value: Any) -> datetime | None:
    """Best-effort ISO-8601 datetime parser."""
    return parse_datetime(value, on_error="none")


def coerce_positive_int(value: Any, *, allow_zero: bool = False, max_value: int | None = None) -> int | None:
    """Coerce a value to a positive integer; return ``None`` on failure."""
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number < 0 or (number == 0 and not allow_zero):
        return None
    if max_value is not None and number > max_value:
        return max_value
    return number


def first_value(*candidates: Any) -> str | None:
    """Return the first non-empty cleaned text value from *candidates*."""
    for candidate in candidates:
        text = clean_text_value(candidate)
        if text:
            return text
    return None


def clean_text_value(value: Any) -> str | None:
    """Sanitise a value to a stripped string or ``None``."""
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, (int, float)):
        return str(value)
    return None


__all__ = [
    "clean_text_value",
    "coerce_entities",
    "coerce_positive_int",
    "coerce_string_list",
    "coerce_time_range",
    "first_value",
    "parse_datetime_value",
]
