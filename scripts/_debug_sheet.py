#!/usr/bin/env python3
"""Diagnostic: read current Google Sheet content."""

from __future__ import annotations

import json

import google.auth
from google.auth import impersonated_credentials
from google.auth.transport.requests import Request as GRequest

SHEET_ID = "1o8iSyLtFbSxdqEtT-L7OQvSqKTealP1H8f0VZzZKTw8"


def _build_creds():
    """Build credentials via SA impersonation (same as setup_feedback_sheet.py)."""
    source_creds, project = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    sa_email = f"sa-app@{project}.iam.gserviceaccount.com"
    print(f"Impersonating {sa_email} (project={project})")
    return impersonated_credentials.Credentials(
        source_credentials=source_creds,
        target_principal=sa_email,
        target_scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
    )


def main() -> None:
    import urllib.request

    creds = _build_creds()
    creds.refresh(GRequest())
    token = creds.token

    def _get(path: str) -> dict:
        url = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}{path}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req) as resp:
            return json.load(resp)

    meta = _get("?fields=sheets.properties")
    print("\n=== TABS ===")
    for s in meta.get("sheets", []):
        p = s["properties"]
        print(f"  [{p['index']}] {p['title']} (sheetId={p['sheetId']})")

    print("\n=== Dashboard A1:N12 ===")
    data = _get("/values/Dashboard!A1:N12")
    rows = data.get("values", [])
    if not rows:
        print("  (empty)")
    for i, row in enumerate(rows, 1):
        print(f"  Row {i:2d}: {row}")


if __name__ == "__main__":
    main()
