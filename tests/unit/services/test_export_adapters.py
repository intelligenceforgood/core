"""Tests for the ExportAdapter protocol and concrete adapters.

Covers CsvAdapter, XlsxAdapter, StixAdapter, and get_adapter().
"""

from __future__ import annotations

import json

import pytest

from i4g.services.export_adapters import (
    CsvAdapter,
    ExportAdapter,
    StixAdapter,
    XlsxAdapter,
    _escape_stix_value,
    _stix_pattern,
    get_adapter,
)

_SAMPLE_ROWS = [
    {"name": "Alice", "amount": 100.0, "category": "bank"},
    {"name": "Bob", "amount": 250.5, "category": "crypto"},
]


# ---------------------------------------------------------------------------
# Protocol checks
# ---------------------------------------------------------------------------


def test_csv_adapter_implements_protocol() -> None:
    """CsvAdapter satisfies ExportAdapter."""
    assert isinstance(CsvAdapter(), ExportAdapter)


def test_xlsx_adapter_implements_protocol() -> None:
    """XlsxAdapter satisfies ExportAdapter."""
    assert isinstance(XlsxAdapter(), ExportAdapter)


def test_stix_adapter_implements_protocol() -> None:
    """StixAdapter satisfies ExportAdapter."""
    assert isinstance(StixAdapter(), ExportAdapter)


# ---------------------------------------------------------------------------
# CsvAdapter
# ---------------------------------------------------------------------------


def test_csv_adapter_serializes_rows() -> None:
    """CsvAdapter produces UTF-8 CSV bytes."""
    adapter = CsvAdapter()
    result = adapter.serialize(_SAMPLE_ROWS)
    assert isinstance(result, bytes)
    text = result.decode("utf-8")
    assert "name,amount,category" in text
    assert "Alice" in text
    assert "Bob" in text


def test_csv_adapter_empty_rows() -> None:
    """CsvAdapter returns empty bytes for no data."""
    assert CsvAdapter().serialize([]) == b""


def test_csv_adapter_content_type() -> None:
    """CsvAdapter returns CSV content type."""
    assert "text/csv" in CsvAdapter().content_type


def test_csv_adapter_custom_columns() -> None:
    """CsvAdapter respects custom column ordering."""
    result = CsvAdapter().serialize(_SAMPLE_ROWS, columns=["category", "name"])
    text = result.decode("utf-8")
    lines = text.strip().split("\n")
    assert lines[0].strip() == "category,name"


# ---------------------------------------------------------------------------
# StixAdapter
# ---------------------------------------------------------------------------


def test_stix_adapter_produces_bundle() -> None:
    """StixAdapter generates a STIX 2.1 bundle."""
    rows = [
        {"indicator_value": "192.168.1.1", "category": "ip", "first_seen": "2025-01-01"},
        {"indicator_value": "evil.com", "category": "domain"},
    ]
    result = StixAdapter().serialize(rows)
    bundle = json.loads(result)
    assert bundle["type"] == "bundle"
    assert len(bundle["objects"]) == 2
    assert bundle["objects"][0]["type"] == "indicator"
    assert bundle["objects"][0]["spec_version"] == "2.1"


def test_stix_adapter_empty() -> None:
    """StixAdapter produces bundle with no objects for empty input."""
    result = StixAdapter().serialize([])
    bundle = json.loads(result)
    assert bundle["objects"] == []


# ---------------------------------------------------------------------------
# XlsxAdapter
# ---------------------------------------------------------------------------


def test_xlsx_adapter_serializes_rows() -> None:
    """XlsxAdapter produces non-empty bytes."""
    result = XlsxAdapter().serialize(_SAMPLE_ROWS)
    assert isinstance(result, bytes)
    assert len(result) > 0


def test_xlsx_adapter_empty_rows() -> None:
    """XlsxAdapter returns empty bytes for no data."""
    assert XlsxAdapter().serialize([]) == b""


# ---------------------------------------------------------------------------
# get_adapter
# ---------------------------------------------------------------------------


def test_get_adapter_csv() -> None:
    """get_adapter('csv') returns CsvAdapter."""
    adapter = get_adapter("csv")
    assert isinstance(adapter, CsvAdapter)


def test_get_adapter_stix() -> None:
    """get_adapter('stix') returns StixAdapter."""
    adapter = get_adapter("stix")
    assert isinstance(adapter, StixAdapter)


def test_get_adapter_invalid_raises() -> None:
    """get_adapter raises ValueError for unknown format."""
    with pytest.raises(ValueError, match="Unsupported"):
        get_adapter("parquet")


# ---------------------------------------------------------------------------
# STIX pattern escaping (S6-H9)
# ---------------------------------------------------------------------------


def test_escape_stix_value_single_quotes() -> None:
    """Single quotes in indicator values are backslash-escaped."""
    assert _escape_stix_value("O'Brien's Account") == "O\\'Brien\\'s Account"


def test_escape_stix_value_backslashes() -> None:
    """Backslashes are escaped before single quotes."""
    assert _escape_stix_value("C:\\Users\\test") == "C:\\\\Users\\\\test"


def test_escape_stix_value_brackets() -> None:
    """Square brackets pass through (they are not special in STIX values)."""
    assert _escape_stix_value("[test]") == "[test]"


def test_escape_stix_value_unicode() -> None:
    """Unicode characters pass through safely."""
    assert _escape_stix_value("café-wallet-日本語") == "café-wallet-日本語"


def test_escape_stix_value_combined() -> None:
    """Combined special characters are escaped correctly."""
    assert _escape_stix_value("val'ue\\path") == "val\\'ue\\\\path"


def test_stix_pattern_bank_account() -> None:
    """Bank account category produces financial-account pattern."""
    pattern = _stix_pattern("1234-5678", "bank_account")
    assert pattern == "[financial-account:account-number = '1234-5678']"


def test_stix_pattern_crypto_wallet() -> None:
    """Crypto wallet category uses cryptocurrency-wallet pattern."""
    pattern = _stix_pattern("0xABC123", "crypto_wallet")
    assert pattern == "[cryptocurrency-wallet:address = '0xABC123']"


def test_stix_pattern_ip_address() -> None:
    """IP category uses ipv4-addr pattern."""
    pattern = _stix_pattern("192.168.1.1", "ip")
    assert pattern == "[ipv4-addr:value = '192.168.1.1']"


def test_stix_pattern_domain() -> None:
    """Domain category uses domain-name pattern."""
    pattern = _stix_pattern("evil.com", "domain")
    assert pattern == "[domain-name:value = 'evil.com']"


def test_stix_pattern_unknown_category() -> None:
    """Unknown category uses fallback x-i4g-indicator pattern."""
    pattern = _stix_pattern("some-value", "unknown")
    assert pattern == "[x-i4g-indicator:value = 'some-value']"


def test_stix_pattern_escapes_dangerous_value() -> None:
    """Values with quotes in pattern are properly escaped."""
    pattern = _stix_pattern("bad'value", "bank")
    assert "bad\\'value" in pattern
    assert pattern == "[financial-account:account-number = 'bad\\'value']"


def test_stix_adapter_category_mapping() -> None:
    """StixAdapter uses category-specific STIX patterns."""
    rows = [
        {"indicator_value": "1234", "category": "bank_account"},
        {"indicator_value": "0xABC", "category": "crypto_wallet"},
    ]
    result = StixAdapter().serialize(rows)
    bundle = json.loads(result)
    patterns = [obj["pattern"] for obj in bundle["objects"]]
    assert "financial-account" in patterns[0]
    assert "cryptocurrency-wallet" in patterns[1]
