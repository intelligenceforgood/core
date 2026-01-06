"""
Manual ad-hoc test script for the review_store FastAPI backend.

This script allows you to quickly verify that the local API endpoints for
case review management (M6 foundation) are functioning as expected.

Run this AFTER launching the API:
    uvicorn i4g.review.api:app --reload

Then in another terminal:
    python tests/adhoc/manual_review_demo.py
"""

import json

import requests

BASE_URL = "http://127.0.0.1:8000"
HEADERS = {"X-API-KEY": "dev-analyst-token"}


def pretty(obj):
    """Pretty-print JSON for better readability."""
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def run_demo():
    print("=== 1. Creating a new review case ===")
    payload = {
        "case_id": "CASE-2025-0001",
        "text": "Hi, this is Anna from TrustWallet. Please send 50 USDT to verify your wallet.",
        "entities": {
            "people": ["Anna"],
            "organizations": ["TrustWallet"],
            "crypto_assets": ["USDT"],
            "wallet_addresses": [],
            "contact_channels": [],
            "locations": [],
            "scam_indicators": ["verification fee", "send to verify"],
        },
        "classification": {
            "intent": [{"label": "INTENT.INVESTMENT", "confidence": 0.93}],
            "channel": [{"label": "CHANNEL.SMS", "confidence": 0.99}],
            "explanation": "The user is asking for a fee to 'verify' a wallet, which is a common crypto scam pattern.",
            "few_shot_examples": [],
        },
        "tags": ["crypto_scam", "urgent"],
    }
    r = requests.post(f"{BASE_URL}/reviews", json=payload, headers=HEADERS)
    r.raise_for_status()
    pretty(r.json())

    print("\n=== 2. Listing all review cases ===")
    r = requests.get(f"{BASE_URL}/reviews/queue", headers=HEADERS)
    r.raise_for_status()
    items = r.json()
    pretty(items)

    if not items.get("items"):
        print("No items in queue.")
        return

    review_id = items["items"][-1]["review_id"]
    print(f"\n=== 3. Getting details for {review_id} ===")
    r = requests.get(f"{BASE_URL}/reviews/{review_id}", headers=HEADERS)
    r.raise_for_status()
    pretty(r.json())


if __name__ == "__main__":
    try:
        run_demo()
    except requests.exceptions.ConnectionError:
        print("❌ Cannot connect to the API. Make sure the FastAPI server is running.")
