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
