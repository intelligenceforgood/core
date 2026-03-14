# Security Audit — TIFAP Sprint 6

**Date:** Sprint 6 Final
**Scope:** Role-based access, PII masking, TLP enforcement, export audit, partner API

## Role-Based Access Control

| Endpoint Pattern               | Required Role | Verified |
| ------------------------------ | ------------- | -------- |
| `GET /intelligence/*`          | analyst+      | Yes      |
| `GET /impact/*`                | analyst+      | Yes      |
| `POST /cases/*/lea-referral`   | analyst+      | Yes      |
| `GET /reports/*`               | analyst+      | Yes      |
| `POST /exports/*`              | analyst+      | Yes      |
| `GET /feeds/indicators`        | partner key   | Yes      |
| `POST /intelligence/campaigns` | admin         | Yes      |
| `DELETE /cases/*`              | admin         | Yes      |

## PII Masking

- Entity stats aggregation anonymizes PII via SHA-256 hashing when records are purged (S1-28)
- Researcher role receives 403 for detail endpoints per S6-H5 decision
- Export files include only analyst-visible fields; PII columns excluded from partner feeds
- Tokenization service (`/tokenization/*`) provides reversible PII masking for authorized users

## TLP Enforcement

- Partner feed API defaults to `TLP:AMBER`
- TLP level is a query parameter, not derived from data — partners receive what they request
- **Recommendation:** Add server-side TLP classification per indicator based on source sensitivity

## Export Audit Logging

- All export operations logged to `audit_log` table via `store.log_action()`
- Partner feed access logged to `partner_feed_audit` table with key_id, endpoint, query params, result count, IP
- Report generation logged via TASK_STATUS tracking

## Partner API Authentication

- Separate from console auth — uses `X-Partner-API-Key` header
- Key storage: SHA-256 hash in `partner_api_keys` table (raw key never stored)
- Key lifecycle: `is_active` flag, `expires_at` timestamp checked on every request
- Rate limiting: per-key, configurable `rate_limit_per_minute` (default: 60)
- Audit: every request logged with response code, IP, query params

## Findings

1. **No critical issues found** — all endpoints properly gated by auth middleware
2. **Low:** TLP enforcement is client-requested, not server-enforced per indicator
3. **Low:** In-memory rate limiting resets on server restart — acceptable until Redis migration
