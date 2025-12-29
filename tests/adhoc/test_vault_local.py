import httpx
import time
import sys

BASE_URL = "http://127.0.0.1:8001"
TOKEN = "dev-analyst-token" # From settings.local.toml

def test_vault_flow():
    headers = {"X-API-KEY": TOKEN}
    
    print("1. Testing Health...")
    try:
        resp = httpx.get(f"{BASE_URL}/tokenization/health", headers=headers)
        resp.raise_for_status()
        print("Health OK:", resp.json())
    except Exception as e:
        print(f"Health check failed: {e}")
        sys.exit(1)

    print("\n2. Testing Tokenize...")
    payload = {
        "value": "test@example.com",
        "prefix": "EID",
        "entity_type": "email"
    }
    resp = httpx.post(f"{BASE_URL}/tokenization/tokenize", json=payload, headers=headers)
    resp.raise_for_status()
    token_data = resp.json()
    print("Tokenize OK:", token_data)
    
    token = token_data["token"]
    assert token.startswith("EID-")
    
    print("\n3. Testing Detokenize...")
    detok_payload = {
        "token": token
    }
    resp = httpx.post(f"{BASE_URL}/tokenization/detokenize", json=detok_payload, headers=headers)
    resp.raise_for_status()
    detok_data = resp.json()
    print("Detokenize OK:", detok_data)
    
    assert detok_data["canonical_value"] == "test@example.com" # Normalized?
    # Wait, normalization logic: EID -> lowercase.
    # Input was "test@example.com" (already lower).
    # If I send "Test@Example.COM", canonical should be normalized?
    # Let's check the code. TokenizationService stores `canonical_value` as the raw input?
    # `self.store.upsert_token(..., canonical_value=value, ...)`
    # So it stores the RAW value as canonical.
    
    print("\n4. Testing Normalization & Determinism...")
    payload2 = {
        "value": "Test@Example.COM", # Mixed case
        "prefix": "EID"
    }
    resp = httpx.post(f"{BASE_URL}/tokenization/tokenize", json=payload2, headers=headers)
    token_data2 = resp.json()
    print("Tokenize 2 OK:", token_data2)
    
    assert token_data2["token"] == token # Should be same token
    assert token_data2["normalized_value"] == "test@example.com"
    
    # Detokenize the second one should return the FIRST canonical value stored?
    # Or does upsert update it?
    # `upsert_token` implies update.
    # If I detokenize now, what do I get?
    resp = httpx.post(f"{BASE_URL}/tokenization/detokenize", json={"token": token}, headers=headers)
    detok_data2 = resp.json()
    print("Detokenize 2 OK:", detok_data2)
    # It probably returns the latest canonical value if upsert updated it.
    
    print("\nSuccess! Vault API is working locally.")

if __name__ == "__main__":
    # Wait for server to start
    time.sleep(2)
    test_vault_flow()
