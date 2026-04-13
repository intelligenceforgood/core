# Victim Contact Decryption & Subpoena SOP

> **Consolidation pending.** This SOP was planned for consolidation into [`../design/pii_protection.md`](../design/pii_protection.md).
> That consolidation is **not yet complete** — `pii_vault.md` covers the encryption design but does not yet contain this operational procedure.
> Until the consolidation is complete, this file remains the authoritative source for decryption and subpoena procedures.
> See `pii_vault.md` for the underlying PII vault design and encryption architecture.

This SOP governs how encrypted victim contact fields may be decrypted for legal requests, investigations, or operational debugging. Apply it to every environment (local sandbox, dev, prod) with stricter enforcement in prod.

## Roles

- **Requester**: submits subpoena/legal request or incident ticket. May not access contact data directly.
- **Approver**: security or privacy lead; secondary approver is backend TL. Dual approval required in prod.
- **Operator**: analyst or SRE/on-call executing the request using audited tooling; must not be the requester.

## Preconditions

- Ticket created with requester identity, scope (intake IDs, case IDs, time range), and legal basis.
- Risk review by approver; in prod require two approvals.
- Operator confirms access via Workload Identity Federation/impersonation; no personal credentials.

## Execution Steps

1. **Access channel**: use `GET /intakes/{id}/contact` endpoint, which decrypts contact fields and emits audit log entries with actor, intake_id, and timestamp.
2. **Least data**: request only required intake records; prefer redacted summaries when possible.
3. **Rate limits**: ensure per-actor throttling is enabled (`contact_decrypt_alert_threshold`); pause if alerts fire.
4. **Validation**: verify case ownership and scope before returning data; reject mismatched cases.
5. **Return path**: deliver results over approved channel (encrypted attachment or secure drive) tied to the ticket ID.

## Logging & Audit

- Every decryption attempt is logged to the `audit_log` table with actor, intake_id, action (`decrypt_contact`), outcome, and timestamp.
- Forward structured logs to SIEM/OTLP.
- Keep logs for ≥ 400 days; do not delete without security approval.

## Alerting

- Trigger `contact_decrypt_access` alert when:
  - Actor exceeds threshold attempts/hour (configure via `I4G_OBSERVABILITY__CONTACT_DECRYPT_ALERT_THRESHOLD`).
  - Access outside business hours for prod.
  - Bulk decryption attempts without prior approval.
- Page security/on-call when alerts fire in prod; create incident tickets.

## Retention & Purge

- Purge decrypted outputs after fulfillment (no local copies). Artifacts stored in secure drive get 30-day TTL unless legal hold applies.
- Key rotation: generate a new Fernet key, re-encrypt existing contact fields, then swap the `I4G_CRYPTO__PII_KEY` secret version.

## Reporting

- Update the ticket with: requester, approvers, operator, time window, intake IDs processed, count of records returned, and link to audit logs.
- For subpoenas, attach proof of legal basis and jurisdictions consulted.

## Testing

- Run a dry-run mode in lower envs using mock data; confirm audit logs emit and alerts trigger under throttle tests before enabling in prod.
