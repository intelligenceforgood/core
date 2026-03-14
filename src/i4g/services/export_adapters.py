"""Export adapter protocol and concrete adapters for entity/indicator export.

Provides a unified interface for serializing analytics data into
CSV, XLSX, and STIX 2.1 formats. Each adapter implements the
``ExportAdapter`` protocol.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ExportAdapter(Protocol):
    """Protocol for data export adapters."""

    @property
    def content_type(self) -> str:
        """MIME content type for the export format."""
        ...

    @property
    def file_extension(self) -> str:
        """File extension (without dot) for the export format."""
        ...

    def serialize(self, rows: list[dict[str, Any]], *, columns: list[str] | None = None) -> bytes:
        """Serialize row data into the target format.

        Args:
            rows: List of row dictionaries.
            columns: Optional column ordering. If omitted, keys from the first row are used.

        Returns:
            Serialized bytes.
        """
        ...


class CsvAdapter:
    """Exports rows as UTF-8 CSV."""

    @property
    def content_type(self) -> str:
        return "text/csv; charset=utf-8"

    @property
    def file_extension(self) -> str:
        return "csv"

    def serialize(self, rows: list[dict[str, Any]], *, columns: list[str] | None = None) -> bytes:
        """Serialize rows to CSV bytes.

        Args:
            rows: List of row dictionaries.
            columns: Optional column ordering.

        Returns:
            UTF-8 encoded CSV bytes.
        """

        if not rows:
            return b""
        cols = columns or list(rows[0].keys())
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        return buf.getvalue().encode("utf-8")


class XlsxAdapter:
    """Exports rows as XLSX using openpyxl (optional dependency).

    Falls back to CSV if openpyxl is not installed.
    """

    @property
    def content_type(self) -> str:
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    @property
    def file_extension(self) -> str:
        return "xlsx"

    def serialize(self, rows: list[dict[str, Any]], *, columns: list[str] | None = None) -> bytes:
        """Serialize rows to XLSX bytes.

        Args:
            rows: List of row dictionaries.
            columns: Optional column ordering.

        Returns:
            XLSX workbook bytes.
        """

        try:
            from openpyxl import Workbook
        except ImportError:
            # Fallback to CSV if openpyxl is not available
            return CsvAdapter().serialize(rows, columns=columns)

        if not rows:
            return b""
        cols = columns or list(rows[0].keys())
        wb = Workbook()
        ws = wb.active
        ws.title = "Export"
        ws.append(cols)
        for row in rows:
            ws.append([row.get(c) for c in cols])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()


class StixAdapter:
    """Exports indicator rows as a STIX 2.1 bundle."""

    @property
    def content_type(self) -> str:
        return "application/json"

    @property
    def file_extension(self) -> str:
        return "json"

    def serialize(self, rows: list[dict[str, Any]], *, columns: list[str] | None = None) -> bytes:
        """Serialize indicator rows to a STIX 2.1 bundle.

        Args:
            rows: List of indicator dictionaries. Expected keys include
                ``indicator_value``, ``category``, ``first_seen``, ``last_seen``.
            columns: Ignored for STIX output.

        Returns:
            JSON-encoded STIX bundle bytes.
        """

        objects: list[dict[str, Any]] = []
        now = datetime.now(UTC).isoformat()

        for row in rows:
            indicator_value = row.get("indicator_value") or row.get("value", "")
            category = row.get("category", "unknown")
            pattern = _stix_pattern(indicator_value, category)
            obj: dict[str, Any] = {
                "type": "indicator",
                "spec_version": "2.1",
                "id": f"indicator--{_deterministic_id(indicator_value, category)}",
                "created": row.get("first_seen", now),
                "modified": row.get("last_seen", now),
                "name": f"{category}: {indicator_value}",
                "pattern": pattern,
                "pattern_type": "stix",
                "valid_from": row.get("first_seen", now),
                "labels": [category],
            }
            objects.append(obj)

        bundle: dict[str, Any] = {
            "type": "bundle",
            "id": f"bundle--{_deterministic_id('export', now)}",
            "objects": objects,
        }
        return json.dumps(bundle, indent=2).encode("utf-8")


def _escape_stix_value(value: str) -> str:
    """Escape a value for safe inclusion in a STIX 2.1 pattern string.

    Escapes backslashes and single quotes per the STIX patterning spec.

    Args:
        value: Raw indicator value.

    Returns:
        Escaped string safe for STIX pattern interpolation.
    """
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _stix_pattern(indicator_value: str, category: str) -> str:
    """Build a category-specific STIX 2.1 pattern with proper escaping.

    Args:
        indicator_value: Raw indicator value.
        category: Indicator category (e.g. ``bank_account``, ``crypto_wallet``).

    Returns:
        STIX 2.1 pattern string.
    """
    escaped = _escape_stix_value(indicator_value)
    if category in ("bank", "bank_account", "ach", "wire"):
        return f"[financial-account:account-number = '{escaped}']"
    if category in ("crypto", "crypto_wallet"):
        return f"[cryptocurrency-wallet:address = '{escaped}']"
    if category in ("ip", "ip_address"):
        return f"[ipv4-addr:value = '{escaped}']"
    if category in ("domain",):
        return f"[domain-name:value = '{escaped}']"
    return f"[x-i4g-indicator:value = '{escaped}']"


def get_adapter(fmt: str) -> ExportAdapter:
    """Return the appropriate adapter for the given format string.

    Args:
        fmt: One of ``csv``, ``xlsx``, or ``stix``.

    Returns:
        An ExportAdapter instance.

    Raises:
        ValueError: If the format is not recognized.
    """

    adapters: dict[str, ExportAdapter] = {
        "csv": CsvAdapter(),
        "xlsx": XlsxAdapter(),
        "stix": StixAdapter(),
    }
    adapter = adapters.get(fmt.lower())
    if adapter is None:
        raise ValueError(f"Unsupported export format: {fmt}")
    return adapter


def _deterministic_id(value: str, salt: str) -> str:
    """Generate a deterministic UUID-like hex string from value and salt."""

    import hashlib

    digest = hashlib.sha256(f"{value}:{salt}".encode()).hexdigest()
    return f"{digest[:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}"
