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
- Keep normalization deterministic and idempotent per prefix; reject values that fail validation rather than emitting bad tokens.
- Store normalization rules in a shared library so ingestion, workers, and services stay aligned.

## Detection & Tokenization Pipeline
- Detect PII in structured ingestion payloads and OCR text from PDFs/screenshots.
- Map each detected value to a prefix; if ambiguous, prefer the stricter validator or fall back to `UNK` with a flag.
- Normalize and validate, then generate the token; drop the original from downstream payloads.
- Write tokens to SQL/Vertex; write canonical PII + metadata to the vault store.

## Vault Storage & Layout
- Vault DB (tokens): table columns for token, full digest, prefix code (FK to prefix registry), encrypted canonical value, normalized hash, case ID, artifact/file ref, detector type/confidence, timestamps, retention markers. A separate prefix registry table holds name/description/validation rules so new prefixes can be added without schema changes.
- Artifact storage (GCS only for source files, not tokens): keep originals in the vault project bucket, top-level by artifact kind (`pdf/`, `png/`, `txt/`, etc.), then shard by content hash (e.g., `pdf/ab/cd/<sha256>.pdf`) to avoid massive single folders regardless of token type or PII density per document.
- Retention: default indefinite; attach lifecycle policies only when legal/policy demands purging specific prefixes or cases.

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
