# Partner API Authentication Guide

This guide covers how external partners and programmatic clients authenticate against the i4g platform using API keys.

---

## 1. Overview & Key Types

The i4g platform supports database-backed API keys for programmatic access without interactive Google Sign-In.

API keys use standard prefix formatting to indicate key purpose:

| Key Type | Prefix Format | Target Persona & Usage |
| :--- | :--- | :--- |
| **Partner** | `i4g_pk_<32_hex_chars>` | External organizations accessing feed & intelligence APIs |
| **User** | `i4g_uk_<32_hex_chars>` | Individual analyst scripts & personal automation |
| **Service** | `i4g_sk_<32_hex_chars>` | Internal backend background jobs & service-to-service |

> [!IMPORTANT]
> **One-Time Display:** Your raw API key is displayed **only once** upon generation. The i4g platform stores only a salted SHA-256 hash of your key. If a key is lost, it cannot be recovered; you must revoke it and generate a new key.

---

## 2. Requesting & Managing API Keys

### Self-Service Key Generation (User & Analyst Keys)
1. Sign in to the i4g Analyst Console (`/settings/api-keys`).
2. Click **Create New Key**.
3. Enter a descriptive name (e.g. `laptop-ingest-script`) and select an expiration period (30 days, 90 days, 1 year, or Never).
4. Copy and securely store the generated key (`i4g_uk_...`).

### Admin-Provisioned Partner Keys
For partner organizations (`i4g_pk_...`):
- Organization administrators contact an i4g platform admin to issue a dedicated partner key with custom scopes (e.g. `partner:feed`, `cases:read`) and per-key rate limits (`rate_limit_per_minute`).

---

## 3. Making Authenticated Requests

Pass your API key in the `X-API-KEY` HTTP header on every request.

### Ingress Endpoints
- **Partner Ingress (Production):** `https://api.i4g.app` (Bypasses Google IAP)
- **Local Development:** `http://localhost:8000`

---

## 4. Code Examples

### cURL

```bash
curl -X GET "http://localhost:8000/api/v1/partner/feed" \
  -H "X-API-KEY: i4g_pk_0123456789abcdef0123456789abcdef" \
  -H "Accept: application/json"
```

### Python (`requests`)

```python
import requests

API_BASE_URL = "http://localhost:8000"
API_KEY = "i4g_pk_0123456789abcdef0123456789abcdef"

headers = {
    "X-API-KEY": API_KEY,
    "Accept": "application/json",
}

response = requests.get(f"{API_BASE_URL}/api/v1/partner/feed", headers=headers)

if response.status_code == 200:
    data = response.json()
    print(f"Retrieved {len(data.get('items', []))} feed items")
elif response.status_code == 401:
    print("Authentication failed: Invalid or expired API key")
elif response.status_code == 403:
    print("Authorization failed: Missing required scope")
elif response.status_code == 429:
    print("Rate limit exceeded: Please back off and retry")
else:
    print(f"Error {response.status_code}: {response.text}")
```

### Python (`httpx` / Async)

```python
import asyncio
import httpx

API_BASE_URL = "http://localhost:8000"
API_KEY = "i4g_pk_0123456789abcdef0123456789abcdef"

async def fetch_partner_feed():
    async with httpx.AsyncClient(headers={"X-API-KEY": API_KEY}) as client:
        response = await client.get(f"{API_BASE_URL}/api/v1/partner/feed")
        response.raise_for_status()
        return response.json()

if __name__ == "__main__":
    feed = asyncio.run(fetch_partner_feed())
    print(feed)
```

---

## 5. Scopes & Role Permissions

Each API key carries an explicit list of authorized scopes:

| Scope | Description | Default Role Minimum |
| :--- | :--- | :--- |
| `partner:feed` | Read-only access to published partner intelligence feed | `partner` / `researcher` |
| `cases:read` | Query anonymized case metadata & indicators | `analyst` |
| `indicators:read` | Query threat indicator database | `analyst` |
| `reports:read` | Download generated intelligence reports | `analyst` |

Admin API keys bypass scope checks. Keys without the required scope receive an `HTTP 403 Forbidden` error.

---

## 6. Expiry, Rotation & Revocation

### Key Expiration & Renewal
- Keys expire automatically at their `expires_at` timestamp.
- Requests with an expired key receive `HTTP 401 Unauthorized`.
- Prior to expiration, generate a new key and update your client application configuration.

### Zero-Downtime Key Rotation
1. Generate a new API key in `/settings/api-keys` or via `POST /api-keys`.
2. Update your downstream application configuration with the new key.
3. Verify successful requests using the new key.
4. Revoke the old key via `DELETE /api-keys/{key_id}`.

### Emergency Revocation
If an API key is compromised:
- Immediately revoke it via the Console UI at `/settings/api-keys` or call `DELETE /api-keys/{key_id}`.
- Active requests using the revoked key will fail immediately on the next request.

---

## 7. Troubleshooting & Error Codes

| Status Code | Reason | Resolution |
| :--- | :--- | :--- |
| `401 Unauthorized` | Invalid, expired, or revoked API key | Check key header formatting (`X-API-KEY`) and key status |
| `403 Forbidden` | Account deactivated or key lacks required scope | Contact administrator to grant required scopes |
| `429 Too Many Requests` | Exceeded `rate_limit_per_minute` | Implement exponential backoff in client requests |
