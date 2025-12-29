"""
Smoke test script for verifying the PII Vault integration in the deployed environment.

Usage:
    python tests/adhoc/smoke_vault_cloud.py --url https://<YOUR_CLOUD_RUN_URL>

Prerequisites:
    - gcloud auth print-identity-token must work (or provide --token)
    - The user must have permission to invoke the Cloud Run service.
"""

import argparse
import json
import subprocess
import sys
import urllib.request
from typing import Dict, Optional


def get_gcloud_token() -> str:
    """Retrieve an identity token using gcloud."""
    try:
        token = subprocess.check_output(
            ["gcloud", "auth", "print-identity-token"], text=True
        ).strip()
        return token
    except subprocess.CalledProcessError as e:
        print(f"Error getting gcloud token: {e}")
        sys.exit(1)


def make_request(
    url: str, endpoint: str, payload: Dict, token: str, api_key: Optional[str] = None
) -> Dict:
    """Make an authenticated POST request to the API."""
    full_url = f"{url.rstrip('/')}/tokenization{endpoint}"
    data = json.dumps(payload).encode("utf-8")
    
    req = urllib.request.Request(full_url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {token}")
    if api_key:
        req.add_header("X-API-KEY", api_key)
    
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code}: {e.reason}")
        print(e.read().decode("utf-8"))
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"URL Error: {e.reason}")
        sys.exit(1)


def run_smoke_test(base_url: str, token: Optional[str] = None, api_key: Optional[str] = None):
    """Run the smoke test sequence."""
    if not token:
        print("Fetching identity token from gcloud...")
        token = get_gcloud_token()

    print(f"Targeting: {base_url}")

    # Test Data
    pii_value = "john.doe@example.com"
    entity_type = "EMAIL"
    
    # 1. Tokenize
    print(f"\n[1] Tokenizing '{pii_value}' ({entity_type})...")
    tokenize_payload = {
        "value": pii_value,
        "entity_type": entity_type,
        "detector": "smoke_test_cloud",
        "case_id": "smoke_case_001"
    }
    token_resp = make_request(base_url, "/tokenize", tokenize_payload, token, api_key)
    
    pii_token = token_resp.get("token")
    if not pii_token:
        print("FAILED: No token returned.")
        sys.exit(1)
        
    print(f"SUCCESS: Got token '{pii_token}'")
    print(f"Payload: {json.dumps(token_resp, indent=2)}")

    # 2. Detokenize
    print(f"\n[2] Detokenizing '{pii_token}'...")
    detokenize_payload = {
        "token": pii_token,
        "case_id": "smoke_case_001"
    }
    detoken_resp = make_request(base_url, "/detokenize", detokenize_payload, token, api_key)
    
    original_value = detoken_resp.get("canonical_value")
    if original_value != pii_value:
        print(f"FAILED: Detokenized value '{original_value}' does not match original '{pii_value}'")
        sys.exit(1)
        
    print(f"SUCCESS: Detokenized value matches original.")
    print(f"Payload: {json.dumps(detoken_resp, indent=2)}")

    print("\nSmoke Test PASSED!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Smoke test PII Vault on Cloud Run")
    parser.add_argument("--url", required=True, help="Base URL of the Cloud Run service")
    parser.add_argument("--token", help="Identity token (optional, defaults to gcloud)")
    parser.add_argument("--api-key", help="API Key for X-API-KEY header", default="dev-analyst-token")
    args = parser.parse_args()
    run_smoke_test(args.url, args.token, args.api_key)
