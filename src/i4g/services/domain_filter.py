"""Domain blocklist filtering for SSI investigation targets.

Prevents automatic investigation of known-legitimate domains such as
``google.com``, ``facebook.com``, etc.  Both exact domain matches and
subdomain matches are supported (e.g. blocking ``google.com`` also
blocks ``mail.google.com``).
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_DEFAULT_DOMAIN_BLOCKLIST: list[str] = [
    "google.com",
    "facebook.com",
    "twitter.com",
    "x.com",
    "instagram.com",
    "linkedin.com",
    "youtube.com",
    "github.com",
    "microsoft.com",
    "apple.com",
    "amazon.com",
    "wikipedia.org",
    "reddit.com",
]


def _extract_domain(url: str) -> str | None:
    """Extract the hostname from a URL string.

    Args:
        url: Raw URL (with or without scheme).

    Returns:
        Lowercased hostname, or ``None`` if extraction fails.
    """
    if not url:
        return None
    try:
        if "://" not in url:
            url = "https://" + url
        parsed = urlparse(url)
        hostname = parsed.hostname
        return hostname.lower() if hostname else None
    except Exception:
        return None


def is_domain_blocked(url: str, blocklist: list[str]) -> bool:
    """Check if a URL's domain is in the blocklist.

    Matches exact domain and subdomains.  For example,
    ``blocklist=['google.com']`` blocks ``mail.google.com`` and
    ``google.com`` but **not** ``notgoogle.com``.

    Args:
        url: URL to check.
        blocklist: List of blocked domain strings.

    Returns:
        ``True`` if the URL's domain matches a blocklist entry.
    """
    domain = _extract_domain(url)
    if not domain:
        return False

    for blocked in blocklist:
        blocked_lower = blocked.lower()
        if domain == blocked_lower or domain.endswith("." + blocked_lower):
            return True

    return False


def get_merged_blocklist(settings_blocklist: list[str]) -> list[str]:
    """Merge settings blocklist with built-in defaults (deduplicated).

    Args:
        settings_blocklist: User-configured blocked domains from settings.

    Returns:
        Combined list of unique blocked domains.
    """
    combined = set(_DEFAULT_DOMAIN_BLOCKLIST)
    combined.update(settings_blocklist)
    return sorted(combined)
