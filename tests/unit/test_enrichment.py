"""Unit tests for passive DNS and ASN enrichment services (S5-30)."""

from __future__ import annotations

from unittest.mock import patch


def test_passive_dns_no_key_returns_error() -> None:
    """When API key is not configured, returns error result."""
    with patch("i4g.services.enrichment.passive_dns._get_api_key", return_value=""):
        from i4g.services.enrichment.passive_dns import lookup_domain

        result = lookup_domain("example.com")
        assert result.error == "api_key_not_configured"
        assert result.records == []


def test_passive_dns_ip_no_key() -> None:
    """IP lookup with no key returns error."""
    with patch("i4g.services.enrichment.passive_dns._get_api_key", return_value=""):
        from i4g.services.enrichment.passive_dns import lookup_ip

        result = lookup_ip("1.2.3.4")
        assert result.error == "api_key_not_configured"


def test_asn_lookup_parse() -> None:
    """RDAP response parsing extracts ASN info correctly."""
    from i4g.services.enrichment.asn_lookup import _parse_rdap_response

    mock_data = {
        "name": "EXAMPLE-NET",
        "startAddress": "1.2.3.0",
        "endAddress": "1.2.3.255",
        "country": "US",
        "cidr0_cidrs": [{"v4prefix": "1.2.3.0", "length": 24}],
        "arin_originas0_originautnums": [12345],
        "entities": [
            {
                "vcardArray": [
                    "vcard",
                    [["version", {}, "text", "4.0"], ["fn", {}, "text", "Example Inc."]],
                ]
            }
        ],
    }

    result = _parse_rdap_response("1.2.3.4", mock_data)
    assert result.ip_address == "1.2.3.4"
    assert result.network_name == "EXAMPLE-NET"
    assert result.cidr == "1.2.3.0/24"
    assert result.asn == "12345"
    assert result.asn_name == "Example Inc."
    assert result.country == "US"


def test_asn_lookup_empty_response() -> None:
    """RDAP response with minimal data doesn't raise."""
    from i4g.services.enrichment.asn_lookup import _parse_rdap_response

    result = _parse_rdap_response("10.0.0.1", {})
    assert result.ip_address == "10.0.0.1"
    assert result.asn is None
    assert result.asn_name is None
