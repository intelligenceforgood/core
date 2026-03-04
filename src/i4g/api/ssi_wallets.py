"""SSI wallet search and export endpoints.

Provides wallet search across all SSI investigations and per-scan
export in CSV and XLSX formats.  These replace the equivalent endpoints
from the standalone ``ssi-api`` service.

* ``GET /investigations/ssi/wallets`` — cross-scan wallet search
* ``GET /investigations/ssi/{scan_id}/wallets.csv`` — CSV export
* ``GET /investigations/ssi/{scan_id}/wallets.xlsx`` — XLSX export
"""

from __future__ import annotations

import csv
import io
import logging
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse

from i4g.api.auth import require_role, require_token
from i4g.api.camel import CamelModel
from i4g.services.factories import build_ssi_store

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/investigations/ssi",
    tags=["ssi", "wallets"],
    dependencies=[Depends(require_token)],
)

# Column spec shared between CSV and XLSX exports.
_EXPORT_COLUMNS: list[tuple[str, str]] = [
    ("wallet_address", "Wallet Address"),
    ("token_symbol", "Token"),
    ("network_short", "Network"),
    ("source", "Source"),
    ("confidence", "Confidence"),
    ("site_url", "Site URL"),
    ("harvested_at", "Harvested At"),
]


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class WalletSearchResponse(CamelModel):
    """Wallet search results."""

    items: list[dict[str, Any]]
    count: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialize_datetimes(row: dict[str, Any]) -> dict[str, Any]:
    """Convert datetime values to ISO-8601 strings in-place.

    Args:
        row: A dict whose values may include ``datetime`` objects.

    Returns:
        The same dict with datetimes converted to strings.
    """
    for key, val in row.items():
        if hasattr(val, "isoformat"):
            row[key] = val.isoformat()
    return row


def _wallet_rows_to_csv(wallets: list[dict[str, Any]]) -> str:
    """Render wallet rows as a CSV string.

    Args:
        wallets: List of wallet dicts from ``SsiStore``.

    Returns:
        UTF-8 CSV content with header row.
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([label for _, label in _EXPORT_COLUMNS])
    for w in wallets:
        writer.writerow([str(w.get(col, "")) for col, _ in _EXPORT_COLUMNS])
    return buf.getvalue()


def _wallet_rows_to_xlsx(wallets: list[dict[str, Any]], path: Path) -> None:
    """Write wallet rows to an XLSX workbook.

    Requires ``openpyxl`` (optional dependency).  Import is deferred so
    the core package does not hard-depend on it.

    Args:
        wallets: List of wallet dicts from ``SsiStore``.
        path: Destination file path.

    Raises:
        RuntimeError: If ``openpyxl`` is not installed.
    """
    try:
        from openpyxl import Workbook
    except ImportError as exc:
        raise RuntimeError("openpyxl is required for XLSX export. Install it with: pip install openpyxl") from exc

    wb = Workbook()
    ws = wb.active
    ws.title = "Wallets"
    ws.append([label for _, label in _EXPORT_COLUMNS])
    for w in wallets:
        ws.append([str(w.get(col, "")) for col, _ in _EXPORT_COLUMNS])
    wb.save(path)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/wallets", response_model=WalletSearchResponse)
def search_wallets(
    address: str | None = Query(None, description="Filter by wallet address."),
    token_symbol: str | None = Query(None, description="Filter by token symbol (e.g. ETH, BTC)."),
    deduplicate: bool = Query(True, description="Deduplicate across scans (default: true)."),
    limit: int = Query(100, ge=1, le=500, description="Max results."),
    _user: dict = Depends(require_role("analyst")),
) -> dict[str, Any]:
    """Search wallet addresses across all SSI investigations.

    Args:
        address: Optional exact wallet address filter.
        token_symbol: Optional token symbol filter (e.g. ``ETH``).
        deduplicate: Deduplicate by address across scans (default ``True``).
        limit: Maximum number of results (1–500).

    Returns:
        Wallet search results with count.
    """
    store = build_ssi_store()
    wallets = store.search_wallets(
        address=address,
        token_symbol=token_symbol,
        limit=limit,
        deduplicate=deduplicate,
    )
    for w in wallets:
        _serialize_datetimes(w)
    return {"items": wallets, "count": len(wallets)}


@router.get(
    "/{scan_id}/wallets.csv",
    tags=["export"],
    responses={
        200: {"content": {"text/csv": {}}},
        404: {"description": "Investigation not found or has no wallets."},
    },
)
def export_wallets_csv(
    scan_id: str,
    _user: dict = Depends(require_role("analyst")),
) -> StreamingResponse:
    """Export wallet addresses for a single investigation as CSV.

    Args:
        scan_id: UUID of the site_scans row.

    Returns:
        Streaming CSV response.

    Raises:
        HTTPException: 404 if the scan or wallets are not found.
    """
    store = build_ssi_store()
    scan = store.get_scan(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Investigation not found.")

    wallets = store.get_wallets(scan_id)
    if not wallets:
        raise HTTPException(status_code=404, detail="No wallets found for this investigation.")

    for w in wallets:
        _serialize_datetimes(w)
    csv_content = _wallet_rows_to_csv(wallets)
    return StreamingResponse(
        io.BytesIO(csv_content.encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="wallets_{scan_id[:8]}.csv"'},
    )


@router.get(
    "/{scan_id}/wallets.xlsx",
    tags=["export"],
    responses={
        200: {"content": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {}}},
        404: {"description": "Investigation not found or has no wallets."},
    },
)
def export_wallets_xlsx(
    scan_id: str,
    _user: dict = Depends(require_role("analyst")),
) -> FileResponse:
    """Export wallet addresses for a single investigation as XLSX.

    Requires ``openpyxl`` (optional dependency).  Returns HTTP 501 if
    the library is not installed.

    Args:
        scan_id: UUID of the site_scans row.

    Returns:
        XLSX file response.

    Raises:
        HTTPException: 404 if the scan or wallets are not found.
        HTTPException: 501 if ``openpyxl`` is not installed.
    """
    store = build_ssi_store()
    scan = store.get_scan(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Investigation not found.")

    wallets = store.get_wallets(scan_id)
    if not wallets:
        raise HTTPException(status_code=404, detail="No wallets found for this investigation.")

    for w in wallets:
        _serialize_datetimes(w)
    tmp_dir = Path(tempfile.mkdtemp(prefix="ssi_export_"))
    filename = f"wallets_{scan_id[:8]}.xlsx"
    output_path = tmp_dir / filename

    try:
        _wallet_rows_to_xlsx(wallets, output_path)
    except RuntimeError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc

    return FileResponse(
        path=str(output_path),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
