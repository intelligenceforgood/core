# PhishDestroy Integration Runbooks

This document outlines the operational procedures required to maintain the PhishDestroy integration.

## 1. Upstream Re-Sync

The PhishDestroy upstream repositories (ScamIntelLogs, DestroyScammers) are periodically updated. To re-sync the I4G environment with the latest upstream data:

1. **Bump Commit SHA**: Update the pinned commit SHAs in the provenance contract (`copilot/.github/shared/phishdestroy-provenance.instructions.md`).
2. **Run Ingestion Jobs**: Execute the following commands to ingest the new data:
   ```bash
   # Ingest archive data
   i4g jobs ingest phishdestroy-archive --path <path-to-ScamIntelLogs-checkout>

   # Ingest actors data
   i4g jobs ingest phishdestroy-actors --path <path-to-DestroyScammers-checkout/data/data.json>
   ```
3. **Verify Ingestion**: Ensure the jobs complete successfully and check the parse-failure reports in `data/reports/phishdestroy/`.

## 2. API-Key Rotation

API keys for external OSINT providers must be rotated according to organizational policy.

**Providers:** merklemap, whoxy, virustotal, urlscan

1. **Generate New Keys**: Obtain new API keys from the respective provider consoles.
2. **Update Configuration**: Update the secret values. For local development, update `core/config/settings.local.toml` and `ssi/config/settings.local.toml`. For production, update the corresponding Secret Manager bindings.
3. **Restart Services**: Restart the `merklemap-tail` and `blocklist-aggregator` Cloud Run jobs/schedulers to pick up the new secrets.

## 3. PII-Access Audit Review

A weekly review of PII access must be conducted to ensure compliance.

1. **Query Audit Logs**: Run the following query against the `audit_log` table to surface all PII access events:
   ```sql
   SELECT timestamp, user_id, action, resource_type, resource_id, reason_code
   FROM audit_log
   WHERE action = 'read' AND resource_type IN ('threat_actors.real_name', 'chat_sessions', 'leak_records')
   ORDER BY timestamp DESC;
   ```
2. **Review Justifications**: Ensure that every access event has a valid `reason_code` and was performed by an authorized user (`role=senior_analyst`).
3. **Report Anomalies**: Report any unauthorized or unjustified access to the security team immediately.

## 4. Google OSINT Session Management

Google persona OSINT (People API, Maps contributions) is now handled natively by SSI
via browser session cookies extracted at runtime. There is no external GHunt dependency.

**How it works:** During an SSI investigation, the orchestrator extracts Google session
cookies (`SID`, `HSID`, `SSID`, `APISID`, `SAPISID`) from the browser before it closes.
If the browser profile is logged into a Google account, these cookies authenticate
requests to Google internal APIs.

1. **Ensure Browser Profile Is Logged In**: The SSI worker's Chromium profile must have
   an active Google session. If the session expires, log in manually via the profile
   or configure persistent login.
2. **Monitor Failures**: If Google OSINT consistently returns empty results, check the
   SSI logs for `"Google OSINT: skipping — no valid Google session cookies available"`.
   This means the browser profile has no active Google session.
3. **No Secrets Required**: Unlike the old GHunt flow, there is no `GHUNT_COOKIE_BLOB`
   secret to rotate. Cookies are extracted live from the browser session.

See: `ssi/src/ssi/osint/google/` for implementation details.
