# Entity Extraction v2 — Architecture

> **Document Version**: 1.0
> **Last Updated**: 2026-04-10
> **Audience**: Engineers, technical stakeholders
> **PRD**: `planning/prd_entity_extraction_v2.md`

---

## Overview

Entity Extraction v2 replaces the scattered extraction logic (inline LLM calls, duplicated merge
heuristics, hard-coded blocklists) with a modular, authority-ranked pipeline. Every entity in the
system flows through a single function: `extract_entities()`.

**Key properties:**

- **Single entry point** — all callers use `i4g.extraction.extract_entities()`
- **Pluggable modules** — new extraction strategies are added by implementing `ModuleProtocol`
- **Authority-ranked merge** — higher-authority modules' confidence counts more
- **Auditable** — every merge decision is recorded with action, reason, and source provenance
- **Configurable** — enabled modules, confidence gates, and blocklists are settings, not code
- **Resilient** — a failed module does not block the pipeline; partial results are returned

---

## Pipeline Flow

```mermaid
flowchart TD
    A["Source text"] --> B["normalize_obfuscated_text()"]
    B --> C["chunk_text()"]
    C --> D["Fan-out to modules"]

    D --> R["RegexModule"]
    D --> H["HeuristicModule"]
    D --> L["LLMModule"]
    D --> M["MLNERModule"]

    R --> E["Collect ScoredEntity lists"]
    H --> E
    L --> E
    M --> E

    E --> F["merge_entities()"]
    F --> G1["Authority-weighted confidence"]
    G1 --> G2["Multi-source agreement bonus"]
    G2 --> G3["Contradiction penalty"]
    G3 --> G4["Confidence gating"]
    G4 --> G5["Blocklist filtering"]
    G5 --> G6["Audit trail"]

    G6 --> Z["ExtractionResult"]
    Z --> Z1["entities: list[ScoredEntity]"]
    Z --> Z2["module_reports: list[ModuleReport]"]
    Z --> Z3["merge_log: list[MergeDecision]"]
```

---

## Module System

### Module Protocol

Every extraction module implements `ModuleProtocol`:

| Property / Method | Type                 | Description                                  |
| ----------------- | -------------------- | -------------------------------------------- |
| `name`            | `str`                | Unique identifier (e.g., `"regex"`, `"llm"`) |
| `authority`       | `dict[str, float]`   | Per-entity-type authority weight in [0, 1]   |
| `extract(text)`   | `list[ScoredEntity]` | Run extraction on normalized text            |

### Module Capability Matrix

| Entity Type    |  Regex  | Heuristic |   LLM   | ML NER | Notes                               |
| -------------- | :-----: | :-------: | :-----: | :----: | ----------------------------------- |
| wallet_address | **1.0** |     —     |   0.7   |  0.6   | Regex is definitive (pattern-based) |
| email_address  | **1.0** |     —     |   0.7   |  0.6   | Regex is definitive                 |
| phone_number   | **1.0** |     —     |   0.7   |  0.6   | Regex is definitive                 |
| url            | **1.0** |     —     |   0.7   |  0.6   | Regex is definitive                 |
| bank_account   |   0.9   |     —     |   0.7   |  0.6   | Regex covers structured formats     |
| social_handle  |   0.9   |     —     |   0.7   |   —    | Regex covers @-prefixed handles     |
| person         |    —    |    0.4    | **0.8** |  0.7   | LLM primary; heuristic corroborates |
| organization   |    —    |     —     | **0.8** |  0.7   | LLM primary                         |
| scam_indicator |    —    |     —     | **0.8** |   —    | LLM only                            |
| location       |    —    |     —     |   0.7   |  0.7   | LLM + ML NER                        |
| crypto_token   |    —    |    0.4    |   0.7   |   —    | Keyword heuristic + LLM             |
| domain         |    —    |     —     |   0.7   |   —    | LLM only                            |

**Bold** = highest authority for that type. Dash = module does not cover that type.

### Module Details

**RegexModule** — Pattern-based extraction for technical entity types (wallets, emails, phones,
URLs, bank accounts, social handles). Confidence is 0.9 for all matches. Highest authority for
pattern-matchable types because regex has zero ambiguity.

**HeuristicModule** — Lightweight rules for person names (capitalized two-word patterns) and crypto
token keywords. Low authority (0.4) because both heuristics are noisy — they require corroboration
from LLM or ML NER to survive the merge.

**LLMModule** — Structured JSON extraction via LLM prompt (Ollama or Vertex AI). Primary source for
semantic entity types (person, organization, scam_indicator). Includes language detection for
non-English texts. Limited to 8,000 characters per call; larger documents are chunked.

**MLNERModule** — Named entity recognition via the ML platform's prediction API. Passes through
model confidence scores (not hard-coded). Requires an active ML serving endpoint.

**BlocklistModule** — Post-extraction filter, not a producer. Called during merge to drop known
false positives (e.g., "Wells Fargo" as person, "On Behalf" as person). Configured via
`config/entity_blocklist.toml`.

---

## Merge Algorithm

The merge engine (`merge.py`) transforms a flat list of `ScoredEntity` from all modules into a
deduplicated, quality-gated result with full provenance.

### Steps

1. **Group** — entities grouped by `(entity_type, canonical_value)`.

2. **Authority-weighted confidence** — for each group, compute:

   ```
   weighted = max(authority[source_module][entity_type] * confidence)
   ```

3. **Multi-source agreement bonus** — if 2+ modules found the same entity:

   ```
   weighted = min(1.0, weighted + 0.1 × (num_sources − 1))
   ```

4. **Contradiction penalty** — for each module with authority ≥ 0.7 for the type that ran
   successfully but did NOT find the entity:

   ```
   weighted *= 0.8
   ```

   Rationale: a high-authority module's silence is evidence against the entity.

5. **Confidence gating** — if `weighted < gate[entity_type]`, the entity is dropped. Default gate
   is 0.5. Per-type gates are configured in `settings.default.toml` (`gate_<type>` keys).

6. **Blocklist filtering** — if `blocklist.is_blocklisted(entity_type, canonical_value)`, the
   entity is dropped regardless of confidence.

7. **Emit** — surviving entities are marked KEPT (single source) or BOOSTED (multi-source). Each
   decision is recorded as a `MergeDecision` audit record.

### Constants

| Constant                    | Value | Purpose                                                      |
| --------------------------- | ----- | ------------------------------------------------------------ |
| `_AGREEMENT_BONUS`          | 0.1   | Added per additional agreeing source                         |
| `_CONTRADICTION_FACTOR`     | 0.8   | Multiplier when high-authority module is silent              |
| `_HIGH_AUTHORITY_THRESHOLD` | 0.7   | Authority level that triggers contradiction check            |
| `_DEFAULT_GATE`             | 0.5   | Fallback confidence gate when no per-type gate is configured |

### Why This Algorithm Works

The authority-ranked merge solves the core problem of the v1 system: regex finding "Wells Fargo"
as a person name and no logic to override it. In v2:

- Regex has **0.0 authority for person** (it doesn't produce person entities at all).
- LLM has **0.8 authority for person** — it correctly identifies "Wells Fargo" as an organization.
- The blocklist adds a safety net: even if a module misclassifies, known false positives are caught.
- The contradiction penalty suppresses entities that only one low-authority module finds.

---

## Text Pre-Processing

Before modules see the text, two transformations run:

### Obfuscation Normalization

Scammers obfuscate contact info to evade detection. The normalizer reverses:

| Technique          | Example                 | Normalized          |
| ------------------ | ----------------------- | ------------------- |
| Spaced characters  | `g o o g l e . c o m`   | `google.com`        |
| Separator words    | `john at gmail dot com` | `john@gmail.com`    |
| Bracket separators | `[at]` / `[dot]`        | `@` / `.`           |
| Leetspeak          | `g00gle`, `b1tc0in`     | `google`, `bitcoin` |

Leetspeak decoding only fires for known scam-related keywords (google, bitcoin, coinbase, etc.)
to avoid false positives on legitimate numeric strings.

### Large Document Chunking

Documents exceeding the LLM's context window are split on message boundaries (email thread
delimiters, paragraph breaks). Each chunk is extracted independently, then entities are
deduplicated across chunks. Span offsets are adjusted to reference the full original document.

---

## Callers

### Entity Extract Job (`worker/jobs/entity_extract.py`)

The batch extraction job queries the database for cases missing entities, fetches their source
document text, and calls `extract_entities()` for each case. Results are persisted to the
`entities` table (and `indicators` for threat infrastructure types). Supports `--backfill` and
`--limit` flags. Concurrency controlled by `extraction.batch_concurrency`.

### Ingest Payloads (`services/ingest_payloads.py`)

At ingest time, `prepare_ingest_payload()` calls `extract_entities(text, modules=["regex"])` as a
fast fallback when no pre-structured entities exist. Regex-only extraction provides immediate
entity availability without LLM latency. The full extraction job runs later to add semantic types.

---

## Configuration

All extraction settings live in `config/settings.default.toml` under `[extraction]`:

| Setting             | Default            | Description                                      |
| ------------------- | ------------------ | ------------------------------------------------ |
| `enabled_modules`   | `["regex", "llm"]` | Modules to run (also: `"heuristic"`, `"ml_ner"`) |
| `batch_concurrency` | `1`                | Parallel LLM calls in batch jobs                 |
| `llm_delay_seconds` | `0.5`              | Throttle between sequential LLM calls            |
| `gate_<type>`       | `0.4`–`0.6`        | Per-type confidence threshold                    |

Override via environment variables: `I4G_EXTRACTION__ENABLED_MODULES='["regex","llm","heuristic"]'`.

The blocklist is in `config/entity_blocklist.toml` — editable by non-engineers. Format:

```toml
[person]
values = ["Wells Fargo", "On Behalf", "United States"]
```

---

## Quality Assurance

The `i4g entity-qa` CLI provides a test harness for measuring extraction quality:

| Command                       | Purpose                                                   |
| ----------------------------- | --------------------------------------------------------- |
| `bundle list/download/create` | Manage labeled test bundles                               |
| `test module <name>`          | Run a single module on a bundle                           |
| `test orchestrator`           | Run full pipeline on a bundle                             |
| `compare`                     | Side-by-side module F1 comparison                         |
| `score`                       | Precision/recall/F1 per entity type against golden labels |
| `report`                      | Combined score + comparison + statistics                  |
| `analyze-fps`                 | Find probable false positives in a large corpus           |
| `blocklist list/add/test`     | Manage the blocklist                                      |

CI enforces a quality gate: PRs that degrade F1 below threshold on `regression-v1` bundle are
blocked.

---

## Module Layout

```
src/i4g/extraction/
├── __init__.py              # Public API: extract_entities() + re-exports
├── types.py                 # ScoredEntity, ExtractionResult, ModuleProtocol, etc.
├── orchestrator.py          # Module registry, fan-out, chunk handling
├── merge.py                 # Authority-ranked merge engine
├── normalize.py             # Obfuscation normalization, entity type/value normalization
├── modules/
│   ├── regex.py             # Pattern-based extraction (wallets, emails, etc.)
│   ├── heuristic.py         # Name/keyword heuristics
│   ├── llm.py               # LLM-based structured extraction
│   ├── ml_ner.py            # ML NER model client
│   └── blocklist.py         # False-positive filter
├── quality/
│   ├── bundle.py            # Test bundle management (cases + golden labels)
│   ├── scorer.py            # Precision/recall/F1 computation
│   ├── metrics.py           # Batch extraction observability
│   └── report.py            # Human-readable + JSON reports
├── ner_rules.py             # Legacy shim (delegates to regex module)
└── semantic_ner.py          # Legacy shim (delegates to llm module)
```

---

## Decision Log

| Decision                                     | Rationale                                                                                    |
| -------------------------------------------- | -------------------------------------------------------------------------------------------- |
| Single `extract_entities()` entry point      | Prevents the v1 problem of scattered extraction logic with inconsistent merge rules          |
| Authority-weighted merge instead of voting   | Simple majority voting would let three noisy modules outvote one precise regex match         |
| Contradiction penalty (high-auth silence)    | If regex (authority 1.0) doesn't find a wallet, an LLM-only wallet claim should be penalized |
| Blocklist as merge filter, not separate pass | Integrating blocklist into merge ensures the audit trail captures why entities were dropped  |
| Obfuscation normalization before extraction  | Running deobfuscation once at the start means all modules benefit from clean text            |
| Regex-only at ingest, full pipeline in batch | Balances immediate entity availability with extraction quality                               |
| Configurable gates in TOML, not code         | Tuning thresholds shouldn't require code changes or deploys                                  |
| TOML blocklist editable by non-engineers     | Pattern: known false positives emerge from analyst feedback, not code review                 |
