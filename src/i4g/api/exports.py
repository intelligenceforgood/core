"""Exports API router — entity and indicator data exports.

Provides endpoints for exporting entity and indicator data in CSV, XLSX,
and STIX 2.1 formats. All export actions are audit-logged. Indicator
values are masked by default (bank accounts show last 4 digits) unless
the caller has sufficient role and passes ``?unmask=true``.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import StreamingResponse

from i4g.api.auth import require_token
from i4g.api.roles import has_role
from i4g.services.factories import build_analytics_store
from i4g.store.analytics_store import AnalyticsStore

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/exports",
    tags=["exports"],
    dependencies=[Depends(require_token)],
)


# ---------------------------------------------------------------------------
# Dependency factories
# ---------------------------------------------------------------------------


def _get_analytics_store() -> AnalyticsStore:
    """Return an AnalyticsStore instance."""
    return build_analytics_store()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BANK_INDICATOR_CATEGORIES = {"bank", "bank_account", "ach", "wire"}


def _mask_indicator_value(value: str, category: str) -> str:
    """Mask indicator values for privacy.

    Bank account numbers show only the last 4 digits. Other values
    are returned unmodified.

    Args:
        value: The raw indicator value.
        category: The indicator category.

    Returns:
        Masked or unmodified value.
    """
    if category.lower() in _BANK_INDICATOR_CATEGORIES and len(value) > 4:
        return "****" + value[-4:]
    return value


def _log_export(user: dict[str, str], scope: str, fmt: str, count: int) -> None:
    """Audit-log an export action.

    Args:
        user: Authenticated user dict.
        scope: What was exported (entities/indicators).
        fmt: Export format (csv/xlsx/stix).
        count: Number of rows exported.
    """
    logger.info(
        "EXPORT_AUDIT user=%s scope=%s format=%s count=%d ts=%s",
        user.get("username", "unknown"),
        scope,
        fmt,
        count,
        datetime.now(UTC).isoformat(),
    )


# ---------------------------------------------------------------------------
# Entity exports (S2-08)
# ---------------------------------------------------------------------------


@router.get("/entities")
def export_entities(
    fmt: str = Query("csv", description="Export format: csv or xlsx"),
    entity_type: str | None = Query(None, description="Filter by entity type"),
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(10000, ge=1, le=100000, description="Max rows"),
    user: dict = Depends(require_token),
    store: AnalyticsStore = Depends(_get_analytics_store),
) -> Response:
    """Export entity stats as CSV or XLSX.

    All exports are audit-logged with user, timestamp, scope, and format.

    Args:
        fmt: Export format (csv or xlsx).
        entity_type: Optional entity type filter.
        status: Optional status filter.
        limit: Max rows to export.
        user: Authenticated user.
        store: Injected AnalyticsStore.

    Returns:
        Streaming file response.
    """
    items = store.list_entity_stats(
        entity_type=entity_type,
        status=status,
        limit=limit,
    )
    _log_export(user, "entities", fmt, len(items))

    if fmt == "xlsx":
        return _export_xlsx(items, "entities")
    return _export_csv(items, "entities")


# ---------------------------------------------------------------------------
# Indicator exports (S2-08)
# ---------------------------------------------------------------------------


@router.get("/indicators")
def export_indicators(
    fmt: str = Query("csv", description="Export format: csv, xlsx, or stix"),
    category: str | None = Query(None, description="Filter by indicator category"),
    unmask: bool = Query(False, description="Show full indicator values (requires analyst+ role)"),
    limit: int = Query(10000, ge=1, le=100000, description="Max rows"),
    user: dict = Depends(require_token),
    store: AnalyticsStore = Depends(_get_analytics_store),
) -> Response:
    """Export indicator stats as CSV, XLSX, or STIX 2.1 JSON.

    Indicator masking (S2-10): bank account numbers show last 4 by default.
    Pass ``?unmask=true`` with analyst or higher role to reveal full values.

    Args:
        fmt: Export format (csv, xlsx, or stix).
        category: Optional category filter.
        unmask: Show full indicator values. Requires analyst+ role.
        limit: Max rows.
        user: Authenticated user.
        store: Injected AnalyticsStore.

    Returns:
        Streaming file response.
    """
    items = store.list_indicator_stats(category=category, limit=limit)

    # Apply masking (S2-10) unless unmasked by authorized user
    if not unmask:
        for item in items:
            item["number"] = _mask_indicator_value(
                item.get("number", ""),
                item.get("category", ""),
            )
    else:
        # Unmask requires analyst+ role
        user_role = user.get("role", "user")
        if not has_role(user_role, "analyst"):
            # Fallback to masked if insufficient role
            for item in items:
                item["number"] = _mask_indicator_value(
                    item.get("number", ""),
                    item.get("category", ""),
                )

    _log_export(user, "indicators", fmt, len(items))

    if fmt == "stix":
        return _export_stix(items)
    if fmt == "xlsx":
        return _export_xlsx(items, "indicators")
    return _export_csv(items, "indicators")


# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------


def _export_csv(items: list[dict[str, Any]], scope: str) -> StreamingResponse:
    """Render items as CSV.

    Args:
        items: List of dicts to export.
        scope: Name for the downloaded file.

    Returns:
        StreamingResponse with CSV content.
    """
    if not items:
        return StreamingResponse(
            iter(["No data"]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{scope}_export.csv"'},
        )

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(items[0].keys()))
    writer.writeheader()
    for item in items:
        # Flatten complex values to JSON strings for CSV
        row = {}
        for k, v in item.items():
            if isinstance(v, (dict, list)):
                row[k] = json.dumps(v)
            else:
                row[k] = v
        writer.writerow(row)

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{scope}_export.csv"'},
    )


def _export_xlsx(items: list[dict[str, Any]], scope: str) -> Response:
    """Render items as XLSX using openpyxl.

    Args:
        items: List of dicts to export.
        scope: Name for the downloaded file.

    Returns:
        Response with binary XLSX content.
    """
    try:
        from openpyxl import Workbook
    except ImportError:
        # Fallback to CSV if openpyxl not available
        logger.warning("openpyxl not installed, falling back to CSV export")
        return _export_csv(items, scope)

    wb = Workbook()
    ws = wb.active
    ws.title = scope

    if items:
        headers = list(items[0].keys())
        ws.append(headers)
        for item in items:
            row = []
            for h in headers:
                v = item.get(h)
                if isinstance(v, (dict, list)):
                    row.append(json.dumps(v))
                else:
                    row.append(v)
            ws.append(row)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{scope}_export.xlsx"'},
    )


def _export_stix(items: list[dict[str, Any]]) -> Response:
    """Render indicators as a STIX 2.1 JSON bundle.

    Creates a STIX Bundle containing Indicator SDOs for each row.

    Args:
        items: List of indicator dicts.

    Returns:
        Response with STIX 2.1 JSON content.
    """
    import uuid

    stix_objects = []
    for item in items:
        indicator_id = item.get("indicator_id", str(uuid.uuid4()))
        category = item.get("category", "unknown")
        number = item.get("number", "")
        item_name = item.get("item", "")
        ind_type = item.get("type", "")

        # Map category to STIX pattern type
        # Escape single quotes to prevent STIX pattern injection
        escaped_number = number.replace("'", "\\'")
        if category in ("bank", "bank_account", "ach", "wire"):
            pattern = f"[financial-account:account-number = '{escaped_number}']"
        elif category in ("crypto", "crypto_wallet"):
            pattern = f"[cryptocurrency-wallet:address = '{escaped_number}']"
        elif category in ("ip", "ip_address"):
            pattern = f"[ipv4-addr:value = '{escaped_number}']"
        elif category in ("domain",):
            pattern = f"[domain-name:value = '{escaped_number}']"
        else:
            pattern = f"[x-i4g-indicator:value = '{escaped_number}']"

        stix_indicator = {
            "type": "indicator",
            "spec_version": "2.1",
            "id": f"indicator--{indicator_id}",
            "created": datetime.now(UTC).isoformat(),
            "modified": datetime.now(UTC).isoformat(),
            "name": f"{category}: {item_name or number}",
            "description": f"Financial indicator type={ind_type} category={category}",
            "pattern": pattern,
            "pattern_type": "stix",
            "valid_from": str(item.get("first_seen_at", datetime.now(UTC).isoformat())),
            "labels": ["malicious-activity"],
            "x_i4g_case_count": item.get("case_count", 0),
            "x_i4g_loss_sum": float(item.get("loss_sum", 0)),
        }
        stix_objects.append(stix_indicator)

    bundle = {
        "type": "bundle",
        "id": f"bundle--{uuid.uuid4()}",
        "objects": stix_objects,
    }

    return Response(
        content=json.dumps(bundle, indent=2, default=str),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="indicators_stix.json"'},
    )
