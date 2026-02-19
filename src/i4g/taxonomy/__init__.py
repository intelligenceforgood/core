"""Fraud taxonomy utilities.

Provides a lightweight helper for mapping machine-readable taxonomy codes
(e.g. ``INTENT.INVESTMENT``) to human-friendly display labels
(e.g. ``Investment``) using the auto-generated ``CODE_TO_LABEL`` map.
"""

from __future__ import annotations

from i4g.taxonomy.data import CODE_TO_LABEL

__all__ = ["get_display_label", "CODE_TO_LABEL"]


def get_display_label(code: str) -> str:
    """Return a human-readable label for a taxonomy code.

    Falls back to a title-cased version of the code suffix when the code
    is not found in the lookup map (e.g. ``INTENT.UNKNOWN`` → ``Unknown``).

    Args:
        code: A taxonomy code such as ``INTENT.INVESTMENT`` or ``CHANNEL.WEB``.

    Returns:
        The human-friendly label string.
    """
    if code in CODE_TO_LABEL:
        return CODE_TO_LABEL[code]
    # Graceful fallback: strip prefix and title-case
    suffix = code.split(".", 1)[-1] if "." in code else code
    return suffix.replace("_", " ").title()
