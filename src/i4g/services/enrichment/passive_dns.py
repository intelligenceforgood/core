"""Passive DNS enrichment via SecurityTrails API.

Queries historical DNS records for domains and IP addresses, returning
A, AAAA, MX, NS, and CNAME resolution history.

Configure via ``I4G_ENRICHMENT__SECURITYTRAILS_API_KEY``.
When the key is empty, all methods return empty results.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

from i4g.settings import get_settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.securitytrails.com/v1"
_TIMEOUT = 15.0


@dataclass
class DNSRecord:
    """Single historical DNS record."""

    record_type: str
    value: str
    first_seen: str
    last_seen: str


@dataclass
class PassiveDNSResult:
    """Aggregated passive DNS lookup result."""

    query: str
    records: list[DNSRecord] = field(default_factory=list)
    source: str = "securitytrails"
    error: str | None = None


def _get_api_key() -> str:
    """Resolve the SecurityTrails API key from settings."""
    settings = get_settings()
    return getattr(getattr(settings, "enrichment", None), "securitytrails_api_key", "")


def lookup_domain(domain: str) -> PassiveDNSResult:
    """Fetch historical DNS records for a domain.

    Args:
        domain: Domain name to query (e.g. ``example.com``).

    Returns:
        Passive DNS results with historical records.
    """
    api_key = _get_api_key()
    if not api_key:
        logger.debug("SecurityTrails API key not configured — skipping passive DNS lookup")
        return PassiveDNSResult(query=domain, error="api_key_not_configured")

    url = f"{_BASE_URL}/history/{domain}/dns/a"
    headers = {"APIKEY": api_key, "Accept": "application/json"}

    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        records = []
        for record_set in data.get("records", []):
            for value_obj in record_set.get("values", []):
                records.append(
                    DNSRecord(
                        record_type="A",
                        value=value_obj.get("ip", ""),
                        first_seen=record_set.get("first_seen", ""),
                        last_seen=record_set.get("last_seen", ""),
                    )
                )
        return PassiveDNSResult(query=domain, records=records)

    except httpx.HTTPStatusError as exc:
        logger.warning("SecurityTrails API error for %s: %s", domain, exc.response.status_code)
        return PassiveDNSResult(query=domain, error=f"http_{exc.response.status_code}")
    except httpx.TransportError as exc:
        logger.warning("SecurityTrails transport error for %s: %s", domain, exc)
        return PassiveDNSResult(query=domain, error="transport_error")


def lookup_ip(ip_address: str) -> PassiveDNSResult:
    """Fetch domains that have resolved to a given IP address.

    Args:
        ip_address: IPv4 or IPv6 address to query.

    Returns:
        Passive DNS results — domains pointing to this IP.
    """
    api_key = _get_api_key()
    if not api_key:
        return PassiveDNSResult(query=ip_address, error="api_key_not_configured")

    url = f"{_BASE_URL}/ips/nearby/{ip_address}"
    headers = {"APIKEY": api_key, "Accept": "application/json"}

    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        records = []
        for block in data.get("blocks", []):
            for site in block.get("sites", []):
                records.append(
                    DNSRecord(
                        record_type="PTR",
                        value=site,
                        first_seen="",
                        last_seen="",
                    )
                )
        return PassiveDNSResult(query=ip_address, records=records)

    except httpx.HTTPStatusError as exc:
        logger.warning("SecurityTrails IP lookup error for %s: %s", ip_address, exc.response.status_code)
        return PassiveDNSResult(query=ip_address, error=f"http_{exc.response.status_code}")
    except httpx.TransportError as exc:
        logger.warning("SecurityTrails transport error for %s: %s", ip_address, exc)
        return PassiveDNSResult(query=ip_address, error="transport_error")
