"""E2E smoke test: watchlist pin → alert flow.

Exercises the full watchlist lifecycle:

1. Pin an entity to the watchlist (POST /intelligence/watchlist)
2. Verify it appears in the list (GET /intelligence/watchlist)
3. Check that alerts can be retrieved (GET /intelligence/watchlist/alerts)
4. Mark all alerts as read (POST /intelligence/watchlist/alerts/read-all)
5. Clean up — remove the entity (DELETE /intelligence/watchlist/{id})

Run with the API server running::

    python tests/adhoc/test_watchlist_e2e.py [BASE_URL]

Defaults to ``http://localhost:8000``.
"""

from __future__ import annotations

import json
import sys

import requests

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
API = f"{BASE_URL}/intelligence"

HEADERS = {"Content-Type": "application/json"}

# Use a dummy auth token for local/dev — adjust to match your env
AUTH_HEADERS = {**HEADERS, "Authorization": "Bearer test-token"}


def _print_step(n: int, title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  Step {n}: {title}")
    print(f"{'='*60}")


def main() -> None:
    """Run the full watchlist E2E smoke test."""
    print(f"Watchlist E2E Smoke Test — target: {BASE_URL}")

    # ------------------------------------------------------------------ 1
    _print_step(1, "Pin entity to watchlist")
    payload = {
        "entityType": "wallet",
        "canonicalValue": "0xSMOKETEST_E2E",
        "alertOnNewCase": True,
        "alertOnLossIncrease": False,
        "note": "E2E smoke test entity",
    }
    resp = requests.post(f"{API}/watchlist", json=payload, headers=AUTH_HEADERS, timeout=10)
    print(f"  POST /watchlist → {resp.status_code}")
    if resp.status_code not in (200, 201):
        print(f"  FAIL: {resp.text}")
        sys.exit(1)

    item = resp.json()
    watchlist_id = item.get("watchlistId") or item.get("watchlist_id")
    print(f"  Created watchlist item: {watchlist_id}")
    print(f"  Response: {json.dumps(item, indent=2)}")

    # ------------------------------------------------------------------ 2
    _print_step(2, "Verify entity in watchlist")
    resp = requests.get(f"{API}/watchlist?limit=100", headers=AUTH_HEADERS, timeout=10)
    print(f"  GET /watchlist → {resp.status_code}")
    if resp.status_code != 200:
        print(f"  FAIL: {resp.text}")
        sys.exit(1)

    data = resp.json()
    items_list = data.get("items", data) if isinstance(data, dict) else data
    found = any((i.get("watchlistId") or i.get("watchlist_id")) == watchlist_id for i in items_list)
    print(f"  Items returned: {len(items_list)}, target found: {found}")
    if not found:
        print("  FAIL: pinned entity not found in list")
        sys.exit(1)

    # ------------------------------------------------------------------ 3
    _print_step(3, "Check alerts endpoint")
    resp = requests.get(f"{API}/watchlist/alerts?limit=10", headers=AUTH_HEADERS, timeout=10)
    print(f"  GET /watchlist/alerts → {resp.status_code}")
    if resp.status_code != 200:
        print(f"  FAIL: {resp.text}")
        sys.exit(1)

    alerts = resp.json()
    alert_list = alerts if isinstance(alerts, list) else alerts.get("items", [])
    print(f"  Alerts returned: {len(alert_list)}")

    # ------------------------------------------------------------------ 4
    _print_step(4, "Mark all alerts read")
    resp = requests.post(f"{API}/watchlist/alerts/read-all", headers=AUTH_HEADERS, timeout=10)
    print(f"  POST /watchlist/alerts/read-all → {resp.status_code}")
    if resp.status_code != 200:
        print(f"  WARN: {resp.text}")

    # ------------------------------------------------------------------ 5
    _print_step(5, "Clean up — remove entity")
    resp = requests.delete(f"{API}/watchlist/{watchlist_id}", headers=AUTH_HEADERS, timeout=10)
    print(f"  DELETE /watchlist/{watchlist_id} → {resp.status_code}")
    if resp.status_code != 200:
        print(f"  WARN: cleanup failed: {resp.text}")

    # Verify removal
    resp = requests.get(f"{API}/watchlist?limit=100", headers=AUTH_HEADERS, timeout=10)
    remaining = resp.json()
    remaining_items = remaining.get("items", remaining) if isinstance(remaining, dict) else remaining
    still_present = any((i.get("watchlistId") or i.get("watchlist_id")) == watchlist_id for i in remaining_items)
    print(f"  Entity still present after delete: {still_present}")

    print(f"\n{'='*60}")
    print("  PASS — Watchlist E2E smoke test completed successfully")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
