# PII Vault Redesign — Protect Victims, Not Perpetrators

**Status:** Proposal
**Author:** CPO review, prompted by analyst feedback
**Supersedes:** [pii_vault.md](pii_vault.md) (current indiscriminate tokenization design)

---

## Problem Statement

Analysts report that the current PII tokenization system **hinders investigation** rather than supporting it. The root cause is a misalignment between the system's design intent and the platform's investigative purpose:

| What the system does                                                                     | What users expect                                                                                       |
| ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| Tokenizes **all** detected entities (emails, wallets, IPs, phones, names) before storage | Only **victim/reporter** personal data should be protected                                              |
| Analysts see tokens like `EID-A1B2C3D4` instead of actual scam email addresses           | Perpetrator indicators (wallet addresses, scam emails, IPs) should be visible as investigation evidence |
| Detokenization requires explicit per-token API calls, is rate-limited and audit-gated    | Investigation data should be immediately available to authorized analysts                               |
| Reports and LLM summaries reference tokens instead of meaningful values                  | Reports should contain actionable intelligence                                                          |

**User feedback (verbatim):**

- "PII is supposed to protect the victims, not the perpetrators."
- "When we ingest cases, the system treats bank accounts, IP addresses, emails as PII and tokenizes them. But these belong to the perpetrators."
- "If we tokenize these entities, it hinders investigation."

---

## Evaluation of Options

### Option A: Classify entities as victim vs perpetrator, tokenize selectively

**Verdict: Not recommended — the challenge is not surmountable with acceptable accuracy.**

Why entity attribution fails:

1. **Mixed freetext.** Victims describe interactions in `summary` and `details` fields where their own contact info and the scammer's are interleaved: _"I emailed support@fakeexchange.com from my account jerry@gmail.com and sent 2 BTC to 1FzWL..."_ The NER prompt extracts `["support@fakeexchange.com", "jerry@gmail.com"]` as emails with no role label.

2. **LLM prompt limitations.** The current `semantic_ner.py` few-shot examples extract entities by type (people, wallet_addresses, contact_channels) but not by role. Adding role attribution to prompts was tested conceptually:
   - Ambiguity: _"Anna from TrustWallet"_ — is Anna the victim, the scammer, or a legitimate company representative?
   - Cross-reference fragility: matching extracted entities against `intake_records.contact_email` catches only the exact reporter contact, not family members, secondary accounts, or previously used handles.
   - Accuracy: even with chain-of-thought prompting, LLM attribution accuracy on real scam reports is unreliable because the victim often describes the scam from a third-person perspective or omits their own details.

3. **False negatives are dangerous.** If the system classifies a victim's phone number as a perpetrator indicator and displays it to all analysts, that is a privacy violation. The cost of misclassification is asymmetric — it is worse to expose a victim's PII than to accidentally tokenize a perpetrator's email.

4. **Entities overlap.** A wallet address might be the victim's (they sent from it) and also relevant as a trace lead. A phone number might be a spoofed victim number reused by the scammer.

**Conclusion:** Automated victim/perpetrator entity classification cannot achieve the reliability required for a privacy decision. We should not build on this approach.

---

### Option B: Keep the tokenization system but auto-detokenize on display

**Verdict: Not recommended — high infrastructure cost for marginal benefit.**

This option would:

- Keep all tokenization/vault/HMAC machinery running during ingestion
- Modify every API endpoint and report template to call `detokenize()` before returning data
- Keep raw PII out of the main SQL tables (only in the vault)

Problems:

- **Defeats the purpose.** If every API response returns cleartext anyway, the token layer provides no functional privacy — it only adds latency and complexity.
- **LLM degradation persists.** During ingestion, `tokenize_text_content()` replaces values in the text _before_ the LLM summarizer runs. The LLM sees `"sent 2 BTC to WLT-A1B2C3D4"` instead of the actual wallet address, degrading summary quality and cross-case correlation.
- **Marginal security.** The threat model addressed (database breach) is real but secondary: if the API auto-detokenizes, any API-level compromise exposes the same data. The main database already sits behind IAM, VPC, and encryption at rest.
- **Engineering overhead.** Every new endpoint, report template, and background job must remember to call detokenize. This is a maintenance trap.

**Conclusion:** The cost/complexity ratio does not justify this approach. It preserves an expensive system that no longer serves its intended user-facing function.

---

### Option C: Retire entity tokenization; protect only victim intake PII ← **Recommended**

**Verdict: Recommended — aligns protection with actual privacy obligations.**

This design:

1. **Stops tokenizing extracted entities.** Wallet addresses, scam emails, IPs, and phone numbers found in case text are **investigation evidence** and are stored and displayed in cleartext.
2. **Protects victim intake data** with targeted encryption and access controls on the structured fields where victims identify themselves.
3. **Reuses existing vault infrastructure** selectively for victim PII only, preserving the engineering investment while eliminating the analyst friction.

---

## Recommended Design: Victim-Only PII Protection

### Scope of protection

| Data category                                       | Source                                                                                                                         | Protection                                                | Rationale                                                                       |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------- | ------------------------------------------------------------------------------- |
| Victim contact info                                 | `intake_records`: `reporter_name`, `contact_email`, `contact_phone`, `contact_handle`, `contact_channel`, `contact_identifier` | Encrypted at rest + access-gated API                      | This is the victim's personal data submitted in confidence                      |
| Victim demographics                                 | `intake_records`: `victim_country`, `victim_age_range`                                                                         | Stored as-is (non-identifying aggregates)                 | Useful for analytics; not individually identifying                              |
| Case entities (wallets, emails, IPs, phones, names) | Extracted from `summary`, `details`, attachments via NER                                                                       | **No tokenization — store and display in cleartext**      | These are perpetrator indicators and investigation evidence                     |
| Case text (summary, details)                        | Victim-submitted freetext                                                                                                      | Selective redaction of victim contact matches (see below) | Prevent accidental exposure of victim's own contact info in investigation views |
| Attachments (PDFs, screenshots)                     | Evidence files                                                                                                                 | Stored as-is with access controls                         | Evidence for investigation; OCR output is not tokenized                         |

### Architecture changes

#### 1. Retire entity tokenization from the ingestion pipeline

Remove the tokenization calls in `IngestPipeline.persist()`:

**Current flow:**

```
extract entities → tokenize_entities() → tokenize_tree(metadata) → tokenize_text_content() → store
```

**New flow:**

```
extract entities → store (cleartext)
```

- Remove calls to `tokenize_entities()`, `tokenize_tree()`, and `tokenize_text_content()` from [src/i4g/store/ingest.py](src/i4g/store/ingest.py).
- Entities in the `entities` table store `canonical_value` as the actual normalized value (not a token).
- Case `text` retains original content with one exception: victim contact redaction (see section 3 below).

#### 2. Protect victim intake fields with application-level encryption

Reuse the existing `TokenizationService` Fernet encryption (or KMS envelope encryption in production) to encrypt victim contact fields before writing to `intake_records`:

```
IntakeService.create_intake():
    encrypt(reporter_name) → intake_records.reporter_name
    encrypt(contact_email) → intake_records.contact_email
    encrypt(contact_phone) → intake_records.contact_phone
    encrypt(contact_handle) → intake_records.contact_handle
```

- The encryption key remains the existing `I4G_CRYPTO__PII_KEY` from Secret Manager.
- Decryption is gated by role (`require_role("analyst")` or a more restrictive `"intake_viewer"` role) plus audit logging.
- A dedicated API endpoint `/intakes/{intake_id}/contact` returns decrypted victim contact info with full audit trail.
- The `/impact/victims` analytics endpoint continues to use aggregated demographics (country, age range) which are not encrypted.

#### 3. Selective victim-contact redaction in case text

When the victim's `contact_email` or `contact_phone` from the intake form appears verbatim in the `summary` or `details` freetext, redact those specific values:

```
if intake.contact_email and intake.contact_email in case_text:
    case_text = case_text.replace(intake.contact_email, "[VICTIM_EMAIL]")
if intake.contact_phone and normalize_phone(intake.contact_phone) in case_text:
    case_text = case_text.replace(normalize_phone(intake.contact_phone), "[VICTIM_PHONE]")
```

This is a **targeted, high-precision operation** — it only redacts values that exactly match the reporter's own contact info. All other entities (perpetrator emails, wallets, etc.) remain visible.

The redacted markers (`[VICTIM_EMAIL]`, `[VICTIM_PHONE]`) signal to analysts that redaction occurred. Analysts with intake access can look up the original value via the protected intake record if needed.

#### 4. Reuse existing vault infrastructure

| Existing component                                     | Disposition                                                                                                                                    |
| ------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `TokenizationService` (HMAC + Fernet)                  | **Keep** — reuse Fernet encryption for intake field encryption. HMAC tokenization becomes optional/dormant.                                    |
| `pii_tokens` table                                     | **Deprecate** — no longer populated during entity ingestion. Retain for historical data and potential victim-contact token storage.            |
| `PiiTokenStore` / `SqlAlchemyPiiTokenStore`            | **Keep** — adapt as the encrypted victim-contact store, or use `intake_records` encrypted columns directly.                                    |
| Detokenization API (`/tokenization/detokenize`)        | **Keep** — repurpose for decrypting victim contact fields. Retain rate limiting and audit logging.                                             |
| Detection pipeline (`detectors.py`, `llm_detector.py`) | **Retire from ingestion.** Could be retained as an opt-in scanner for compliance audits (e.g., "does this report accidentally contain SSNs?"). |
| Observability (`observability.py`)                     | **Keep** — adapt metrics to track victim-contact encryption/decryption events instead of entity tokenization coverage.                         |
| PII backfill job (`pii_backfill.py`)                   | **Repurpose** — use for migration: decrypt existing tokenized entities back to cleartext in the entities table.                                |
| Pepper, KMS key infrastructure                         | **Keep** — shared with intake encryption. No Terraform changes needed.                                                                         |

### Migration plan

#### Phase 1: Stop tokenizing new ingestions

1. Add a feature flag `I4G_PII__ENTITY_TOKENIZATION_ENABLED=false` (default: `false`).
2. When disabled, `IngestPipeline.persist()` skips `tokenize_entities()`, `tokenize_tree()`, `tokenize_text_content()`.
3. New cases are ingested with cleartext entities.
4. Existing tokenized cases remain as-is until Phase 2.

#### Phase 2: Backfill existing cases

1. Repurpose the `pii_backfill` worker job to iterate over existing cases.
2. For each case: look up entity tokens in `pii_tokens`, retrieve canonical values, update `entities.canonical_value` with the cleartext value.
3. For text content: reverse `tokenize_text_content()` by replacing tokens with canonical values from the vault.
4. Log all backfill operations for audit.

#### Phase 3: Implement victim-contact encryption

1. Add encryption/decryption to `IntakeService.create_intake()` and a new `GET /intakes/{id}/contact` endpoint.
2. Implement selective victim-contact redaction in the ingestion text pipeline.
3. Migrate existing `intake_records` to encrypt the contact fields in place.

#### Phase 4: Clean up

1. Remove the entity tokenization code paths (behind the feature flag).
2. Archive the `pii_tokens` table (or drop after verifying all canonical values are recovered).
3. Update the PII vault design doc to reflect the new scope.
4. Update analyst-facing docs to explain that entities are now visible directly.

---

## Impact on existing features

| Feature                    | Current behavior                                                                               | New behavior                                                                             |
| -------------------------- | ---------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| **Search results**         | Entity values shown as tokens (`EID-A1B2C3D4`)                                                 | Entity values shown in cleartext (`scammer@evil.com`)                                    |
| **Case detail view**       | Text contains tokens; entities are tokens                                                      | Text is cleartext (except victim contact redactions); entities are cleartext             |
| **Reports**                | Generated with tokens; LLM summarizes tokenized text                                           | Generated with real values; LLM sees actual content — higher quality summaries           |
| **Cross-case correlation** | Tokens are deterministic so correlation works, but analysts can't see what they're correlating | Cleartext values — analysts can immediately see shared wallets, emails, IPs across cases |
| **Detokenization API**     | Used frequently by analysts to decode every entity                                             | Rarely used — only for accessing victim contact info from intake records                 |
| **Intake records**         | Contact fields stored as cleartext (current gap)                                               | Contact fields encrypted at rest, access-gated and audit-logged                          |
| **Impact analytics**       | Aggregated victim demographics from intake                                                     | No change — demographics remain non-encrypted aggregates                                 |

## Security and compliance considerations

1. **Victim privacy is strengthened.** Currently, `intake_records.contact_email` and `reporter_name` are stored in cleartext — a gap. The redesign encrypts these fields and gates access.

2. **Perpetrator data is not PII under investigation context.** Wallet addresses, scam email accounts, and IPs used in fraud are investigative indicators, not personal data requiring protection. They are analogous to evidence in a law enforcement case file.

3. **Attack surface is reduced.** The current system has a large attack surface: HMAC pepper, encryption keys, tokenization service, detokenization service, vault storage, and audit logging — all for data that analysts need in cleartext. The redesign narrows the attack surface to victim-contact encryption only.

4. **Audit trail is preserved.** Every access to victim contact info is still logged with actor, reason, case, and timestamp.

5. **Compliance with data protection regulations.** Victim contact data (reporter's personal details) is the data that falls under GDPR, CCPA, and similar regulations. Investigation evidence (perpetrator indicators) is processed under a different legal basis (legitimate interest / law enforcement cooperation).

## Open items

- [ ] Confirm with legal whether any jurisdictions require tokenizing perpetrator identifiers (unlikely for investigation platforms, but worth confirming).
- [ ] Decide whether to keep the PII detection pipeline as an opt-in compliance scanner (e.g., flag cases that accidentally contain SSNs or credit card numbers in freetext).
- [ ] Determine if the selective victim-contact redaction (Phase 3) should be a hard redaction or a soft marker that analysts can reveal with permission.
- [ ] Plan the backfill job ordering — cases with active investigations should be prioritized.
- [ ] Update the referenced `compliance.md` (currently missing) to align with the new PII scope.
