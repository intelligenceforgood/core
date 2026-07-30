# Runbook: API Key Management & Incident Response

**Target Audience:** On-call engineers, system administrators, security response team
**Applies to:** `core`, `infra`, `ui`

---

## 1. Context & Overview

The i4g platform utilizes a unified `api_keys` database table storing salted SHA-256 key hashes for programmatic authentication. This runbook covers administrative tasks, key rotation, usage auditing, and emergency credential containment.

---

## 2. Admin Workflows

### 2.1 Provisioning Partner API Keys via Admin API

To issue a partner key for an external organization:

```bash
curl -X POST "https://api.i4g.app/api/v1/admin/api-keys/partner" \
  -H "X-API-KEY: <ADMIN_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "partner_name": "ACME Security Research",
    "owner_email": "contact@acme.org",
    "scopes": ["partner:feed", "indicators:read"],
    "expires_in_days": 365,
    "rate_limit_per_minute": 120
  }'
```

Output contains the raw key (`i4g_pk_...`) — transmit this securely to the partner via a secure secret-sharing tool (e.g. Password Pusher or Bitwarden Send).

### 2.2 Provisioning via Analyst Console UI
1. Navigate to `/admin/users` in the Analyst Console.
2. Locate the partner user row and click **API Keys**.
3. Select **Create Partner Key**.
4. Fill in partner name, email, scopes, and expiration period.
5. Copy the displayed key before closing the modal.

---

## 3. Auditing Key Usage & Activity

### 3.1 Inspect Active Keys in Database

Connect to Cloud SQL or local database via psql / SQLite CLI:

```sql
-- List all active API keys with owner and expiration details
SELECT key_id, key_prefix, owner_email, key_type, scopes, rate_limit_per_minute, is_active, expires_at, last_used_at
FROM api_keys
WHERE is_active = true
ORDER BY last_used_at DESC NULLS LAST;

-- Inspect keys created for a specific partner or email
SELECT key_id, key_prefix, key_type, is_active, expires_at, last_used_at
FROM api_keys
WHERE owner_email = 'partner@example.com';
```

### 3.2 Correlate Access Logs with Audit Trail

```sql
-- Inspect partner feed access log correlated with key owner
SELECT a.timestamp, a.client_ip, a.partner_name, k.owner_email, k.key_prefix
FROM partner_feed_audit a
LEFT JOIN api_keys k ON a.partner_name = k.owner_email OR a.partner_name = k.key_prefix
ORDER BY a.timestamp DESC
LIMIT 50;
```

---

## 4. Incident Response & Containment

### 4.1 Single Key Revocation (UI / API)

If a single key is reported compromised or leaked in git:

**Via Admin API:**
```bash
curl -X DELETE "https://api.i4g.app/api/v1/admin/api-keys/<KEY_ID>" \
  -H "X-API-KEY: <ADMIN_KEY>"
```

**Via Console UI:**
1. Go to `/admin/users` → **API Keys**.
2. Click **Revoke** next to the target key.
3. Confirm revocation.

### 4.2 Single Key Soft Revocation via Direct SQL (Emergency Break-Glass)

```sql
UPDATE api_keys
SET is_active = false, updated_at = NOW()
WHERE key_id = '<TARGET_KEY_ID>' OR key_prefix = 'i4g_pk_abc12345';
```

### 4.3 Bulk Emergency Revocation (Leak or Incident)

If an entire partner organization's credentials or admin account is compromised:

```sql
-- Deactivate ALL keys belonging to a specific compromised email
UPDATE api_keys
SET is_active = false, updated_at = NOW()
WHERE owner_email = 'compromised_user@example.com' AND is_active = true;

-- Deactivate ALL keys of a specific type (emergency break-glass)
UPDATE api_keys
SET is_active = false, updated_at = NOW()
WHERE key_type = 'partner' AND is_active = true;
```

---

## 5. Maintenance & Rotation Procedures

### 5.1 Routine Key Rotation (90 Days)
1. Issue new key using `POST /admin/api-keys/partner` or Console UI.
2. Deliver key to partner team.
3. Partner updates downstream environment variable.
4. Allow 48-hour grace period during which both keys remain active.
5. Verify `last_used_at` timestamp on new key.
6. Revoke old key.

### 5.2 Cleanup of Expired Keys

Expired keys remain in the table with `is_active=true` but `expires_at < NOW()`. Validation checks handle expiration automatically. To soft-deactivate expired keys in bulk:

```sql
UPDATE api_keys
SET is_active = false, updated_at = NOW()
WHERE expires_at IS NOT NULL AND expires_at < NOW() AND is_active = true;
```
