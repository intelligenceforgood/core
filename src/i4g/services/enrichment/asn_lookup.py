"""ASN enrichment via RDAP (RIPE/ARIN).

Queries the RDAP bootstrap service to resolve IP addresses to ASN
information including organization name, country, and network range.

No API key required — RDAP is a public protocol.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_RDAP_BOOTSTRAP_URL = "https://rdap.org/ip"
_TIMEOUT = 10.0


@dataclass
class ASNInfo:
    """Autonomous System Number information for an IP address."""

    ip_address: str
    asn: str | None = None
    asn_name: str | None = None
    network_name: str | None = None
    country: str | None = None
    cidr: str | None = None
    start_address: str | None = None
    end_address: str | None = None
    source: str = "rdap"
    error: str | None = None


def lookup_ip(ip_address: str) -> ASNInfo:
    """Query RDAP for ASN and network information.

    Uses the RDAP bootstrap redirect at ``rdap.org`` which routes to
    the appropriate RIR (RIPE, ARIN, APNIC, etc.) automatically.

    Args:
        ip_address: IPv4 or IPv6 address to query.

    Returns:
        ASN information for the IP.
    """
    url = f"{_RDAP_BOOTSTRAP_URL}/{ip_address}"

    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(url, headers={"Accept": "application/rdap+json"})
            resp.raise_for_status()
            data = resp.json()

        return _parse_rdap_response(ip_address, data)

    except httpx.HTTPStatusError as exc:
        logger.warning("RDAP lookup error for %s: %s", ip_address, exc.response.status_code)
        return ASNInfo(ip_address=ip_address, error=f"http_{exc.response.status_code}")
    except httpx.TransportError as exc:
        logger.warning("RDAP transport error for %s: %s", ip_address, exc)
        return ASNInfo(ip_address=ip_address, error="transport_error")
    except (KeyError, ValueError) as exc:
        logger.warning("RDAP parse error for %s: %s", ip_address, exc)
        return ASNInfo(ip_address=ip_address, error="parse_error")


def _parse_rdap_response(ip_address: str, data: dict) -> ASNInfo:
    """Extract ASN details from an RDAP IP network response.

    Args:
        ip_address: Queried IP.
        data: Raw RDAP JSON response.

    Returns:
        Populated ASN info.
    """
    info = ASNInfo(ip_address=ip_address)
    info.network_name = data.get("name")
    info.start_address = data.get("startAddress")
    info.end_address = data.get("endAddress")
    info.country = data.get("country")

    # Extract CIDR from handle or cidrs
    cidrs = data.get("cidr0_cidrs", [])
    if cidrs:
        first = cidrs[0]
        info.cidr = f"{first.get('v4prefix') or first.get('v6prefix')}/{first.get('length')}"

    # Extract ASN from arin_originas0_originautnums or remarks
    origin_autnums = data.get("arin_originas0_originautnums", [])
    if origin_autnums:
        info.asn = str(origin_autnums[0])

    # Extract org name from entities
    for entity in data.get("entities", []):
        vcard = entity.get("vcardArray")
        if vcard and len(vcard) > 1:
            for entry in vcard[1]:
                if entry[0] == "fn":
                    info.asn_name = entry[3]
                    break
        if info.asn_name:
            break

    return info
