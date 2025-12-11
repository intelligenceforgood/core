# PII Vault Design (Dec 2025)

**Audience:** proto engineers/architects. End-user guidance will stay in the separate `docs/` repo; this file is technical.

## Goals
- Tokenize all detected PII (structured fields and OCR text) into `AAA-XXXXXXXX` tokens before it touches SQL/Vertex.
- Keep tokens deterministic across environments by sharing a versioned HMAC pepper (stored in each vault via KMS).
- Preserve canonical PII and source artifacts in the vault with subpoena-grade detokenization controls and full audit trails.
- Avoid hot folders by sharding artifact storage paths and keep retention effectively indefinite unless legal requires purge.

## Token Format
- Token shape: `AAA-XXXXXXXX` (3-char uppercase prefix + 8-char hex from HMAC-SHA256 digest).
- Generation: normalize value → validate per type → HMAC(value + prefix + versioned pepper) → hex digest → first 8 chars.
- Collision handling: check digest collision for same prefix; if collision, append a short disambiguator while retaining the canonical digest.
- Determinism: use a shared, versioned pepper replicated to each environment; rotate by adding a new pepper version and re-tokenizing as needed.

## HMAC Scheme & Rotation
- Algorithm: HMAC-SHA256(value || prefix || version) with a KMS-wrapped pepper (stored in Secret Manager, encrypted by vault KMS key). Use a distinct key per env but the same pepper version material to keep tokens stable across envs.
- Output: store full digest; publish first 8 hex chars as token suffix. On collision, append a short disambiguator while preserving the canonical digest for lookup.
- Versioning: include `pepper_version` in the HMAC input and in the tokens table. Add new versions (do not destroy old), then re-tokenize as needed. Disable old versions only after rewrap/migration and health checks.
- Access: only the tokenization service and detokenization path can read the pepper; enforce IAM + audit on Secret Manager + KMS usage.
- Rotation playbook: create new pepper version → update tokenization service config → re-tokenize impacted records (backfill if required) → monitor collision/latency → schedule prior version disablement after 30 days.
- Provisioning: Terraform creates the Secret Manager container `tokenization-pepper` per vault project (no versions); seed
  versions out-of-band (manual or CI) using `gcloud secrets versions add tokenization-pepper --data-file=- --project
  <vault-project>`. Keep the pepper value only in SM; KMS keys live in `i4g-vault-ring/i4g-vault-encrypt`.
- Data encryption: Terraform also creates the `pii-tokenization-key` Secret Manager container and the KMS key
  `i4g-vault-encrypt`; add secret versions manually (same pattern as the pepper) only when you need an application-level
  symmetric key. Do not store secret values in Terraform/state.

## App Integration (Cloud Run)
- Secrets: read the HMAC pepper from `tokenization-pepper` (Secret Manager, vault project) and, if used, an application
  symmetric key from `pii-tokenization-key`. Both are provisioned as secret containers via Terraform; versions are added
  manually/CI.
- Deployment wiring: set Cloud Run env vars from secrets (example):
  `gcloud run services update <svc> --set-secrets="I4G_TOKENIZATION__PEPPER=tokenization-pepper:latest,I4G_CRYPTO__PII_KEY=pii-tokenization-key:latest"`
  using the app runtime service account that has `secretAccessor` on the vault project and KMS encrypter/decrypter where
  needed.
- Determinism: use the same pepper value in dev/prod when identical input should map to the same token across envs.
- Duplication: stop storing pepper/key material in app projects; all secrets should come from the vault project via
  Workload Identity. Remove any legacy env vars or app-local secrets once the Cloud Run mapping is in place.
- Regression: add a startup check that fails fast when secret access is denied or the value is empty; surface a clear
  error suggesting `secretAccessor` + correct secret ID. Cover this with unit/integration tests that mock Secret Manager
  denial and missing versions.
- Smoke: deploy a Cloud Run dev service with the vault SA bindings, read `tokenization-pepper` via runtime secrets, run
  a tokenization + detokenization round trip against the vault API, and log the token + normalized value (not the raw
  PII). Treat this as the promotion gate for prod.

## Prefix Catalog (initial)
- Identity / contact
  - `EID` email (lowercase, trim, punycode)
  - `NAM` person name (collapse whitespace, strip honorifics)
  - `PHN` phone (E.164)
  - `ADR` address (normalize abbreviations)
  - `DOB` date of birth (ISO date)
- Government / identity numbers
  - `TIN` SSN/TIN/national ID (format-aware)
  - `PID` passport/driver ID
  - `SID` student ID
  - `EMP` employer/employee ID
  - `ETX` employer tax ID
  - `STX` student transcript/record ID
  - `GOV` generic govt ID bucket when country-specific format is unknown
- Financial
  - `CCN` credit/debit card (Luhn)
  - `BAN` bank account (non-IBAN)
  - `IBN` IBAN (modulus check)
  - `RTN` routing/ABA (weight check)
  - `SWF` SWIFT/BIC
  - `ACH` ACH/direct-debit mandate IDs
- Crypto
  - `BTC` bitcoin (base58/bech32)
  - `ETH` ethereum (EIP-55 checksum)
  - `WLT` generic wallet when chain is unknown
- Network / device
  - `IPA` IP address
  - `ASN` autonomous system number
  - `MAC` MAC/device address
  - `DID` generic device/advertising ID (IDFA/GAID/etc.)
  - `BFP` browser/device fingerprint ID
  - `CID` cookie/session identifier
- Health / insurance / medical
  - `HID` health insurance/member ID (country/plan aware)
  - `MRN` medical record number (site-specific checksum when known)
  - `NHI` national health ID (country-specific)
- Biometric
  - `BIO` biometric template hash (face/voice/fingerprint embeddings)
- Legal / vehicle
  - `VIN` vehicle VIN
  - `LPL` license plate (jurisdiction tagged)
  - `DOC` document/record ID for case-specific artifacts
- Location
  - `LOC` geolocation coordinate (lat/long rounded to policy)
  - `PLC` place ID when captured from providers
- Fallback
  - `UNK` for low-confidence/unknown types until refined

## Normalization & Validation
- Deterministic, idempotent, reject-on-invalid per prefix. Implement as a shared library used by ingestion + services.
- Identity/contact: emails lowercase + trim + punycode; names collapse whitespace/strip honorifics; phones to E.164; addresses normalize common abbreviations and collapse whitespace; DOB to ISO date.
- Gov IDs: SSN/TIN/national IDs strip separators and run format/country checks; passport/driver uppercase + strip separators with country/region length/charset checks; student/employer IDs strip separators, length bounds; employer tax IDs run checksum when applicable; generic `GOV` only when no specific validator passes.
- Financial: cards strip separators + Luhn; bank accounts strip separators + country length rules; IBAN uppercase/strip spaces + modulus 97 check; routing/ABA numeric with weighted checksum; SWIFT/BIC uppercase with length/charset check; ACH IDs strip separators, length bounds.
- Crypto: BTC base58 or bech32 validate; ETH strip 0x, enforce checksum/EIP-55; `WLT` fallback when chain unknown but address passes generic length/charset.
- Network/device: IP canonical IPv4/IPv6; ASN numeric; MAC uppercase hex strip separators; device/advertising IDs lowercase strip separators with length check; browser fingerprint/cookie IDs enforce length/charset bounds.
- Health/medical: insurance/member IDs run plan/country length/charset rules when known; MRN site-specific checksum/length when available; national health IDs country format checks.
- Biometric: only accept hashed/encoded templates (no raw biometrics); enforce expected hash/encoding length and charset.
- Legal/vehicle: VIN uppercase, strip separators, validate check digit; license plates uppercase and tagged with jurisdiction; `DOC` IDs uppercase/strip separators, length bounds.
- Location: geocoordinates normalized to fixed precision (e.g., 5–6 decimals) and validated for range; place IDs validated per provider pattern.
- Fallback: `UNK` used only when detectors are low confidence or validators disagree.

## Detection & Tokenization Pipeline
- Structured detection: use schema-aware detectors for known fields (email, phone, account numbers, names, addresses, IDs). Apply per-prefix normalization/validation before tokenization; if validation fails, drop to `UNK` or flag for review.
- OCR/unstructured detection: run OCR on PDFs/screenshots, then apply pattern/ML detectors for the full prefix set. Prefer high-precision patterns first; only emit tokens when validation passes. Attach detector confidence + spans for audit.
- Disambiguation: if multiple prefixes match, pick the stricter validator (e.g., IBAN over generic bank) or fall back to `UNK` when confidence is low.
- Tokenization flow: normalize → validate → HMAC to token; remove raw PII from downstream payloads; store canonical PII + detector metadata in vault.
- Routing: tokens go to SQL/Vertex; encrypted PII + metadata to vault DB; artifacts to vault GCS.
- Rollback guard: if detector confidence is below threshold or validation fails, do not tokenize; log and optionally queue for manual/secondary pass.
- Sampling harness: sample detected/undetected text and structured fields, record FP/FN metrics per prefix, and iterate detector/rule tuning.

## Vault Storage & Layout
- Vault DB (tokens): table columns for token, full digest, prefix code (FK to prefix registry), encrypted canonical value, normalized hash, case ID, artifact/file ref, detector type/confidence, timestamps, retention markers. A separate prefix registry table holds name/description/validation rules so new prefixes can be added without schema changes.
- Artifact storage (GCS only for source files, not tokens): keep originals in the vault project bucket, top-level by artifact kind (`pdf/`, `png/`, `txt/`, etc.), then shard by content hash (e.g., `pdf/ab/cd/<sha256>.pdf`) to avoid massive single folders regardless of token type or PII density per document.
- Retention: default indefinite; attach lifecycle policies only when legal/policy demands purging specific prefixes or cases.

## Vault Data Model
- Tokens table (core fields): `token` (PK), `full_digest`, `prefix_code` (FK), `encrypted_value`, `encryption_key_version`, `normalized_hash`, `case_id`, `artifact_ref`, `detector` (type/confidence/span), `pepper_version`, `created_at`, `updated_at`, `retention_tag`.
- Prefix registry: `code` (PK), `name`, `description`, `category`, `status`, `validation_rules` (JSON), `min_confidence`, timestamps.
- Artifacts: stored in GCS and referenced by `artifact_ref` (path + hash); integrity hash stored alongside token record for quick verification.

## Artifact Handling
- Storage: dedicated vault bucket per env with IAM limited to vault services. Organize by artifact kind (`pdf/`, `png/`,
  `txt/`, `json/`, `ocr/`, etc.), then shard by SHA-256 (`pdf/ab/cd/<sha256>.pdf`) to prevent hot folders regardless of
  PII density. Do not key paths on token type to keep layout stable during prefix growth.
- Metadata: compute SHA-256 at ingest and persist alongside `artifact_ref` (path, hash, content type, size, case_id,
  uploader/source, created_at). Treat artifacts as immutable; allow dedupe by reusing the same object when hashes match;
  writes occur only from the tokenization pipeline.
- Integrity: write SHA-256 into object metadata and the tokens table; verify upload by comparing hash + size and record
  the GCS generation. Detokenization may revalidate hash on read before release when policy requires.
- Verification job: scheduled worker (Cloud Run + Scheduler) walks shard prefixes, recomputes SHA-256, compares to
  stored hash/size, and emits alerts on missing/mismatched artifacts. Also checks bucket retention/holds against
  `retention_tag` to avoid accidental expiry.
- Lifecycle: default indefinite retention; keep bucket lifecycle rules disabled unless legal/policy mandates purge. When
  purge is required, delete the GCS object and clear references after logging the action; apply object holds for legal
  cases to prevent deletion until explicitly lifted.

## Detokenization Service
- Workflow: validate requester (IAM/IAP), require dual approval or subpoena flag, fetch token record, decrypt `encrypted_value` with KMS-wrapped key, return canonical value + artifact pointers. All attempts audited.
- Controls: rate limit per user/IP/token; deny on missing approvals; log actor, reason, case, prefix, result. Alert on anomalies (rare prefixes, burst requests, repeated failures).
- Interface: gRPC/HTTP service behind internal auth; callable by backend jobs that generate reports or fulfill lawful requests. Returns normalized value plus metadata (prefix, detector confidence, artifact refs).

## Retention, Purge, and Re-key
- Retention: default indefinite; support `retention_tag` to mark legal hold or purge-after dates. Lifecycle policies applied to artifacts only when required.
- Pepper/key rotation: add new versions, re-tokenize/re-encrypt as needed, disable old versions after verification window.
- Purge: when legally required, delete token row, encrypted value, and associated artifacts; emit audit event. Support soft-delete markers to prevent re-ingest of purged PII.

## Prefix Registry & Config
- Registry table (example columns): `code` (PK), `name`, `description`, `category` (identity/gov/financial/etc.), `status` (active/deprecated), `validation_rules` (JSON), `min_confidence`, `created_at`, `updated_at`.
- Tokens table references registry via `prefix_code`; do not hardcode prefixes in services—load from registry/config at startup.
- Validation rules JSON: includes normalization parameters (e.g., regex, checksum type, min/max length, geo precision) and detector hints (preferred patterns, disambiguation priority). Keep rule versions to allow future changes without data migration.
- Config-driven detectors: detectors/tokenizers fetch the registry/rules and apply them dynamically so new prefixes can ship via config/DB, not code. Fallback to `UNK` when no rule matches or confidence is low.

## Detokenization & Access Control
- Detokenization service enforces dual approval/subpoena workflow, KMS-gated decryption, rate limits, and IP/user allowlists.
- Log every attempt with actor, reason, case, prefix, result, and timing; alert on unusual patterns (spikes, rare prefixes, repeated failures).
- Return the canonical value and artifact pointers only after approvals succeed.

## Observability & Quality
- Emit metrics: tokenization coverage, detector confidence bands, collision counts, detokenization attempts/denials, and latency.
- Run sampling harnesses to measure false positives/negatives across prefixes; tune detectors iteratively.
- Include smoke tests that perform tokenization + detokenization round trips from Cloud Run using vault-bound credentials.

## Open Items
- Confirm any additional prefixes needed; extend catalog with the same normalization/validation rigor.
- Decide whether to support reversible redaction for specific document types in addition to tokenization.
- Finalize legal retention exceptions per jurisdiction and wire them into lifecycle policies when required.
