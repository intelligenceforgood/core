#!/usr/bin/env python3
"""Set up the Google Sheet for the Feedback feature.

Creates one tab per console page with standardized header rows and column formatting.
Uses Application Default Credentials (run `gcloud auth application-default login` first).

Usage:
    # Normal run (adds missing tabs, leaves existing data intact):
    conda run -n i4g python scripts/setup_feedback_sheet.py

    # Recreate all tabs from scratch (DELETES ALL DATA on the 16 feedback tabs):
    conda run -n i4g python scripts/setup_feedback_sheet.py --recreate
"""

from __future__ import annotations

import sys
import time
from argparse import ArgumentParser

import google.auth
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SHEET_ID = "1o8iSyLtFbSxdqEtT-L7OQvSqKTealP1H8f0VZzZKTw8"

# Tab name → page route (for reference; route is not written to the sheet)
TABS: dict[str, str] = {
    "Dashboard": "/dashboard",
    "Search": "/search",
    "Accounts": "/accounts",
    "Discovery": "/discovery",
    "Cases": "/cases",
    "Case Detail": "/cases/[id]",
    "Case Intake": "/cases/intake",
    "Dossiers": "/reports/dossiers",
    "Campaigns": "/campaigns",
    "Taxonomy": "/taxonomy",
    "Analytics": "/analytics",
    "SSI Investigate": "/ssi",
    "SSI Investigations": "/ssi/investigations",
    "SSI Investigation Detail": "/ssi/investigations/[id]",
    "SSI Wallets": "/ssi/wallets",
    "Admin Users": "/admin/users",
}

HEADERS = [
    "Timestamp",  # A
    "Page",  # B
    "Section",  # C
    "Type",  # D
    "Priority",  # E
    "Subject",  # F
    "Description",  # G
    "Submitter",  # H
    "Status",  # I
    "Owner",  # J
    "Effort",  # K
    "Page URL",  # L
    "User Agent",  # M
    "Resolution Notes",  # N
]

# Column widths in pixels (14 columns A–N)
COLUMN_WIDTHS = [160, 100, 120, 120, 100, 250, 400, 200, 100, 150, 60, 280, 220, 300]

# Colours
HEADER_BG = {"red": 0.216, "green": 0.278, "blue": 0.31}  # #37474F
HEADER_FG = {"red": 1.0, "green": 1.0, "blue": 1.0}  # #FFFFFF
WHITE = {"red": 1.0, "green": 1.0, "blue": 1.0}


def _hex_to_rgb(h: str) -> dict[str, float]:
    """Convert a 6-digit hex colour to a Sheets API RGB object."""
    h = h.lstrip("#")
    return {
        "red": int(h[0:2], 16) / 255.0,
        "green": int(h[2:4], 16) / 255.0,
        "blue": int(h[4:6], 16) / 255.0,
    }


# Conditional-format rules: (column_index, value, hex_bg)
COND_FORMATS: list[tuple[int, str, str]] = [
    # D — Type
    (3, "Bug", "#FFD7D7"),
    (3, "Feature Request", "#D7E8FF"),
    (3, "UX Issue", "#FFE8CC"),
    (3, "Question", "#FFF9C4"),
    (3, "Other", "#F0F0F0"),
    # E — Priority
    (4, "P0-Critical", "#F4CCCC"),
    (4, "P1-High", "#FCE5CD"),
    (4, "P2-Medium", "#FFF2CC"),
    (4, "P3-Low", "#EFEFEF"),
    # I — Status
    (8, "New", "#D7E8FF"),
    (8, "Accepted", "#D9EAD3"),
    (8, "In Progress", "#FFF2CC"),
    (8, "Done", "#C9DAF8"),
    (8, "Won't Fix", "#F0F0F0"),
    # K — Effort
    (10, "XS", "#D9EAD3"),
    (10, "S", "#B6D7A8"),
    (10, "M", "#FFF2CC"),
    (10, "L", "#FCE5CD"),
    (10, "XL", "#F4CCCC"),
]

# Data validation dropdown values per column index
DROPDOWNS: dict[int, list[str]] = {
    3: ["Bug", "Feature Request", "UX Issue", "Question", "Other"],  # Type
    4: ["P0-Critical", "P1-High", "P2-Medium", "P3-Low"],  # Priority
    8: ["New", "Accepted", "In Progress", "Done", "Won't Fix"],  # Status
    10: ["XS", "S", "M", "L", "XL"],  # Effort
}


def _build_service():
    """Build the Sheets API service.

    Tries SA impersonation first; falls back to user credentials via gcloud CLI token.
    """
    import subprocess

    from google.oauth2.credentials import Credentials as OAuthCredentials

    # Try 1: user's gcloud token (works for personal Sheets access)
    try:
        token = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()
        creds = OAuthCredentials(token=token)
        svc = build("sheets", "v4", credentials=creds)
        # Smoke test
        svc.spreadsheets().get(spreadsheetId=SHEET_ID, fields="spreadsheetId").execute()
        print("Authenticated with gcloud user credentials")
        return svc
    except Exception as exc:
        print(f"User credentials failed ({exc}), trying SA impersonation...")

    # Try 2: SA impersonation
    from google.auth import impersonated_credentials

    source_creds, project = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    sa_email = f"sa-app@{project}.iam.gserviceaccount.com"

    target_creds = impersonated_credentials.Credentials(
        source_credentials=source_creds,
        target_principal=sa_email,
        target_scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    print(f"Authenticated via SA impersonation: {sa_email} (project: {project})")
    return build("sheets", "v4", credentials=target_creds)


def _get_existing_tabs(service) -> dict[str, int]:
    """Return mapping of tab title → sheetId for all existing tabs."""
    meta = service.spreadsheets().get(spreadsheetId=SHEET_ID).execute()
    return {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta.get("sheets", [])}


def _recreate_tabs(service) -> dict[str, int]:
    """Delete all 16 feedback tabs and recreate them from scratch.

    A temporary sheet is created first so the API never sees zero sheets
    (which would be rejected).
    """
    existing = _get_existing_tabs(service)
    feedback_tabs_to_delete = [name for name in existing if name in TABS]

    # Create a temporary placeholder so we can safely delete everything else.
    tmp_name = "_setup_tmp"
    add_resp = (
        service.spreadsheets()
        .batchUpdate(
            spreadsheetId=SHEET_ID,
            body={"requests": [{"addSheet": {"properties": {"title": tmp_name}}}]},
        )
        .execute()
    )
    tmp_id = add_resp["replies"][0]["addSheet"]["properties"]["sheetId"]
    print(f"Created temporary tab '{tmp_name}' (id={tmp_id})")

    # Delete all old feedback tabs.
    if feedback_tabs_to_delete:
        delete_requests = [{"deleteSheet": {"sheetId": existing[name]}} for name in feedback_tabs_to_delete]
        service.spreadsheets().batchUpdate(
            spreadsheetId=SHEET_ID,
            body={"requests": delete_requests},
        ).execute()
        print(f"Deleted {len(feedback_tabs_to_delete)} tabs: {', '.join(feedback_tabs_to_delete)}")

    # Create all feedback tabs fresh.
    add_requests = [{"addSheet": {"properties": {"title": name}}} for name in TABS]
    service.spreadsheets().batchUpdate(
        spreadsheetId=SHEET_ID,
        body={"requests": add_requests},
    ).execute()
    print(f"Created {len(TABS)} fresh tabs")

    # Delete the temporary placeholder.
    service.spreadsheets().batchUpdate(
        spreadsheetId=SHEET_ID,
        body={"requests": [{"deleteSheet": {"sheetId": tmp_id}}]},
    ).execute()
    print(f"Deleted temporary tab '{tmp_name}'")

    # Re-fetch final mapping.
    meta = service.spreadsheets().get(spreadsheetId=SHEET_ID).execute()
    return {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta.get("sheets", [])}


def _create_tabs(service, existing: dict[str, int]) -> dict[str, int]:
    """Create missing tabs and return tab_name → sheetId mapping."""
    to_create = [name for name in TABS if name not in existing]
    if to_create:
        requests = [{"addSheet": {"properties": {"title": name}}} for name in to_create]
        service.spreadsheets().batchUpdate(spreadsheetId=SHEET_ID, body={"requests": requests}).execute()
        print(f"Created {len(to_create)} tabs: {', '.join(to_create)}")
    else:
        print("All tabs already exist")

    # Re-fetch to get sheetIds
    meta = service.spreadsheets().get(spreadsheetId=SHEET_ID).execute()
    return {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta.get("sheets", [])}


def _write_headers(service, tab_sheet_ids: dict[str, int]) -> None:
    """Write header row to each tab."""
    data = []
    for tab_name in TABS:
        if tab_name in tab_sheet_ids:
            data.append(
                {
                    "range": f"'{tab_name}'!A1:{chr(65 + len(HEADERS) - 1)}1",
                    "values": [HEADERS],
                }
            )

    if data:
        service.spreadsheets().values().batchUpdate(
            spreadsheetId=SHEET_ID,
            body={"valueInputOption": "RAW", "data": data},
        ).execute()
        print(f"Wrote headers to {len(data)} tabs")


def _format_tabs(service, tab_sheet_ids: dict[str, int]) -> None:
    """Apply comprehensive formatting to all tabs.

    Per-tab:
    - Header row (row 1): Montserrat bold 10pt, white text on #37474F background,
      WRAP, MIDDLE alignment.
    - Data rows (rows 2+): Inter 10pt, WRAP, TOP alignment, white background.
    - Freeze row 1.
    - Column widths.
    - Dropdown validation on Type / Priority / Status / Effort.
    - Conditional formatting (TEXT_EQ) on Type (col D) and Priority (col E).
    """
    requests = []
    num_cols = len(HEADERS)
    last_col_letter = chr(ord("A") + num_cols - 1)  # "N" for 14 cols
    _ = last_col_letter  # referenced in header-write step only

    for tab_name in TABS:
        sheet_id = tab_sheet_ids.get(tab_name)
        if sheet_id is None:
            continue

        # ── Header row: Montserrat bold, white text, dark background, WRAP ──
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": 1,
                        "startColumnIndex": 0,
                        "endColumnIndex": num_cols,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": HEADER_BG,
                            "textFormat": {
                                "bold": True,
                                "fontFamily": "Montserrat",
                                "fontSize": 10,
                                "foregroundColor": HEADER_FG,
                            },
                            "wrapStrategy": "WRAP",
                            "verticalAlignment": "MIDDLE",
                        }
                    },
                    "fields": (
                        "userEnteredFormat("
                        "backgroundColor,"
                        "textFormat.bold,"
                        "textFormat.fontFamily,"
                        "textFormat.fontSize,"
                        "textFormat.foregroundColor,"
                        "wrapStrategy,"
                        "verticalAlignment)"
                    ),
                }
            }
        )

        # ── Data rows: Inter 10pt, white background, black text, WRAP, TOP ─
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "endRowIndex": 1000,
                        "startColumnIndex": 0,
                        "endColumnIndex": num_cols,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": WHITE,
                            "textFormat": {
                                "bold": False,
                                "fontFamily": "Inter",
                                "fontSize": 10,
                                "foregroundColor": {"red": 0.0, "green": 0.0, "blue": 0.0},
                            },
                            "wrapStrategy": "WRAP",
                            "verticalAlignment": "TOP",
                        }
                    },
                    "fields": (
                        "userEnteredFormat("
                        "backgroundColor,"
                        "textFormat.bold,"
                        "textFormat.fontFamily,"
                        "textFormat.fontSize,"
                        "textFormat.foregroundColor,"
                        "wrapStrategy,"
                        "verticalAlignment)"
                    ),
                }
            }
        )

        # ── Freeze row 1 ────────────────────────────────────────────────────
        requests.append(
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": sheet_id,
                        "gridProperties": {"frozenRowCount": 1},
                    },
                    "fields": "gridProperties.frozenRowCount",
                }
            }
        )

        # ── Column widths ───────────────────────────────────────────────────
        for col_idx, width in enumerate(COLUMN_WIDTHS):
            requests.append(
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "COLUMNS",
                            "startIndex": col_idx,
                            "endIndex": col_idx + 1,
                        },
                        "properties": {"pixelSize": width},
                        "fields": "pixelSize",
                    }
                }
            )

        # ── Dropdown validation ─────────────────────────────────────────────
        for col_idx, values in DROPDOWNS.items():
            requests.append(
                {
                    "setDataValidation": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 1,
                            "endRowIndex": 1000,
                            "startColumnIndex": col_idx,
                            "endColumnIndex": col_idx + 1,
                        },
                        "rule": {
                            "condition": {
                                "type": "ONE_OF_LIST",
                                "values": [{"userEnteredValue": v} for v in values],
                            },
                            "showCustomUi": True,
                            "strict": False,
                        },
                    }
                }
            )

        # ── Conditional formatting for Type (D) and Priority (E) ────────────
        for col_idx, value, hex_color in COND_FORMATS:
            requests.append(
                {
                    "addConditionalFormatRule": {
                        "rule": {
                            "ranges": [
                                {
                                    "sheetId": sheet_id,
                                    "startRowIndex": 1,
                                    "startColumnIndex": col_idx,
                                    "endColumnIndex": col_idx + 1,
                                }
                            ],
                            "booleanRule": {
                                "condition": {
                                    "type": "TEXT_EQ",
                                    "values": [{"userEnteredValue": value}],
                                },
                                "format": {"backgroundColor": _hex_to_rgb(hex_color)},
                            },
                        },
                        "index": 0,
                    }
                }
            )

    if requests:
        # Batch in chunks of 100 to avoid API limits
        for i in range(0, len(requests), 100):
            chunk = requests[i : i + 100]
            service.spreadsheets().batchUpdate(spreadsheetId=SHEET_ID, body={"requests": chunk}).execute()
            if i + 100 < len(requests):
                time.sleep(1)
        print(f"Applied formatting ({len(requests)} operations across {len(TABS)} tabs)")


def _delete_default_sheet(service, tab_sheet_ids: dict[str, int]) -> None:
    """Delete the default 'Sheet1' tab if it exists and is empty."""
    default_name = "Sheet1"
    sheet_id = tab_sheet_ids.get(default_name)
    if sheet_id is None:
        return

    # Check if it has any data
    result = service.spreadsheets().values().get(spreadsheetId=SHEET_ID, range=f"'{default_name}'!A1:A2").execute()
    if result.get("values"):
        print(f"Keeping '{default_name}' — it has data")
        return

    try:
        service.spreadsheets().batchUpdate(
            spreadsheetId=SHEET_ID,
            body={"requests": [{"deleteSheet": {"sheetId": sheet_id}}]},
        ).execute()
        print(f"Deleted empty '{default_name}' tab")
    except HttpError:
        print(f"Could not delete '{default_name}' — skipping")


def _parse_args():
    """Parse command-line arguments."""
    parser = ArgumentParser(description="Set up the i4g feedback Google Sheet.")
    parser.add_argument(
        "--recreate",
        action="store_true",
        help=(
            "Delete all 16 feedback tabs and recreate them from scratch. "
            "WARNING: this destroys all existing feedback data."
        ),
    )
    return parser.parse_args()


def main() -> None:
    """Set up the feedback Google Sheet."""
    args = _parse_args()

    print(f"Setting up feedback sheet: {SHEET_ID}")
    if args.recreate:
        print("MODE: --recreate  (all existing feedback data will be DELETED)")
    print(f"Tabs: {len(TABS)}  |  Columns: {len(HEADERS)} (A–{chr(ord('A') + len(HEADERS) - 1)})")
    print()

    try:
        service = _build_service()
    except Exception as exc:
        print(f"Auth failed: {exc}")
        print("Run: gcloud auth application-default login")
        sys.exit(1)

    if args.recreate:
        print("Recreating all tabs...")
        tab_sheet_ids = _recreate_tabs(service)
    else:
        existing = _get_existing_tabs(service)
        print(f"Existing tabs: {set(existing) or '(none)'}")
        tab_sheet_ids = _create_tabs(service, existing)

    _write_headers(service, tab_sheet_ids)
    _format_tabs(service, tab_sheet_ids)

    if not args.recreate:
        _delete_default_sheet(service, tab_sheet_ids)

    print()
    print("Done! Sheet is ready for feedback collection.")
    print(f"Columns: {', '.join(HEADERS)}")
    print(f"URL: https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit")


if __name__ == "__main__":
    main()
