"""Boolean coercion and environment-variable helpers.

Consolidates ``_coerce_bool`` and ``_env_bool`` helpers that were previously
duplicated across ``intake_job_runner.py`` and ``worker/jobs/dossier_queue.py``.
"""

from __future__ import annotations

import os

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}


def coerce_bool(value: str | None) -> bool | None:
    """Coerce a string value to a boolean.

    Args:
        value: A string that may represent a boolean, or ``None``.

    Returns:
        ``True`` for truthy tokens (``1``, ``true``, ``yes``, ``on``),
        ``False`` for falsy tokens (``0``, ``false``, ``no``, ``off``),
        ``None`` if *value* is ``None`` or unrecognised.
    """
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in _TRUTHY:
        return True
    if normalized in _FALSY:
        return False
    return None


def env_bool(name: str, default: bool = False) -> bool:
    """Read an environment variable as a boolean.

    Args:
        name: Environment variable name.
        default: Value returned when the variable is unset.

    Returns:
        ``True`` if the env-var value is a known truthy token, *default*
        otherwise (including when the variable is absent).
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUTHY


def env_int(name: str, default: int) -> int:
    """Read an environment variable as an integer.

    Args:
        name: Environment variable name.
        default: Value returned when the variable is unset or empty.

    Returns:
        The parsed integer value.

    Raises:
        ValueError: If the value cannot be converted to ``int``.
    """
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def env_list(name: str) -> list[str]:
    """Read a comma-separated environment variable as a list of strings.

    Args:
        name: Environment variable name.

    Returns:
        List of stripped, lowercased non-empty tokens.
    """
    raw = os.getenv(name)
    if not raw:
        return []
    return [item.strip().lower() for item in raw.split(",") if item.strip()]
