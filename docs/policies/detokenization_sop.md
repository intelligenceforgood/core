# Detokenization & Subpoena SOP

This SOP governs how tokenized PII may be detokenized for legal requests, investigations, or operational debugging. Apply it to every environment (local sandbox, dev, prod) with stricter enforcement in prod.

## Roles
- **Requester**: submits subpoena/legal request or incident ticket. May not access vault directly.
- **Approver**: security or privacy lead; secondary approver is backend TL. Dual approval required in prod.
- **Operator**: SRE/on-call executing the request using audited tooling; must not be the requester.

## Preconditions
- Ticket created with requester identity, scope (case IDs, prefixes, time range), and legal basis.
- Risk review by approver; in prod require two approvals.
- Operator confirms access via Workload Identity Federation/impersonation; no personal credentials.

## Execution Steps
1. **Access channel**: use detokenization API/CLI with `PiiVaultObservability` enabled to emit `pii.detokenization.attempt` and `pii.detokenization.alert` logs plus metrics.
2. **Least data**: request only required prefixes and cases; prefer redacted or aggregated returns when possible.
3. **Rate limits**: ensure per-actor throttling is enabled; pause if alerts fire.
4. **Validation**: verify case ownership and scope before returning data; reject mismatched cases.
5. **Return path**: deliver results over approved channel (encrypted attachment or secure drive) tied to the ticket ID.

## Logging & Audit
- Every attempt must log actor, prefixes, outcome, reason, case_id, and timestamp.
- Store audit entries in the vault project (Secret Manager/KMS-protected) and forward structured logs to SIEM/OTLP.
- Keep logs for ≥ 400 days; do not delete without security approval.

## Alerting
- Trigger `pii.detokenization.alert` when:
  - Actor exceeds N attempts/hour (configure per environment).
  - Access outside business hours for prod.
  - Prefixes include sensitive categories (e.g., gov ID, biometric) without dual approval.
- Page security/on-call when alerts fire in prod; create incident tickets.

## Retention & Purge
- Follow vault retention policy: purge detokenized outputs after fulfillment (no local copies). Artifacts stored in secure drive get 30-day TTL unless legal hold applies.
- Re-keying: when KMS pepper rotates, rewrap stored secrets before further detokenizations; verify using a canary token.

## Reporting
- Update the ticket with: requester, approvers, operator, time window, prefixes/cases processed, count of records returned, and link to audit logs.
- For subpoenas, attach proof of legal basis and jurisdictions consulted.

## Testing
- Run a dry-run mode in lower envs using mock data; confirm logs/metrics emit and alerts trigger under throttle tests before enabling in prod.
