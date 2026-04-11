# Entity Extraction v2 — Handoff

> **Date**: 2026-04-10
> **Status**: Sprint 6 complete (documentation, migration plan, legacy cleanup, bundle expansion)

---

## Quality Baseline

### Test Bundles

| Bundle            | Cases | Labels | Purpose                                                            |
| ----------------- | ----- | ------ | ------------------------------------------------------------------ |
| `regression-v1`   | 20    | 20     | CI regression gate — all major scam types                          |
| `bad-examples-v1` | 14    | 14     | Known false positives (Wells Fargo, On Behalf, etc.)               |
| `expanded-v1`     | 51    | 51     | Non-English, obfuscated, email threads, short texts, zero entities |

### How to Measure

```bash
conda run -n i4g I4G_PROJECT_ROOT=$PWD I4G_ENV=local I4G_LLM__PROVIDER=mock \
    i4g entity-qa score --bundle regression-v1 --save
```

The regression-v1 bundle with `--threshold 0.8` is the CI quality gate.

---

## Known Limitations

1. **LLM dependency for semantic types.** Person, organization, and scam_indicator extraction
   requires an LLM (Ollama or Vertex AI). The heuristic module provides low-confidence person
   extraction as a fallback, but it is noisy and cannot identify organizations or scam indicators.

2. **ML NER module requires serving endpoint.** The ML NER module is only active when an ML
   platform endpoint is configured. Without it, the system relies on LLM + regex + heuristic.

3. **Non-English precision.** The LLM module handles non-English text via language-aware prompts,
   but regex patterns are language-agnostic (only captures technical patterns like wallets/emails).
   Person/org extraction in non-English scripts depends entirely on LLM quality.

4. **Obfuscation coverage.** The de-obfuscation normalizer handles common patterns (dot/at
   substitution, leetspeak, spaced characters) but scammers constantly invent new techniques.
   The normalizer's keyword allowlist must be manually updated.

5. **Entity relationship extraction.** The system extracts individual entities but does not detect
   relationships between them (e.g., "Person X sent money to Wallet Y"). This was a Sprint 5
   stretch goal and remains unimplemented. The intelligence graph currently infers connections
   via co-occurrence.

6. **Confidence calibration.** Module confidence scores are heuristic (regex=0.9, LLM=0.7,
   heuristic=0.5). They are not calibrated against actual precision. Future work could use the
   golden bundles to calibrate per-module per-type confidence.

7. **IBAN/SWIFT parsing.** Bank account extraction via regex catches numeric sequences but IBAN
   validation is limited. Some legitimate account-like numbers (long phone numbers, ZIP codes)
   may be mis-extracted as bank accounts.

---

## Runbook: Operating the Extraction System

### Daily Operations

The extraction system runs automatically:

- **At ingest time**: regex-only extraction via `ingest_payloads.py` (fast, immediate)
- **In batch**: full orchestrator via `entity-extract` Cloud Run job (scheduled/manual)

No daily manual intervention is needed.

### Monitoring

After each batch run, check:

1. **Entity counts per type** — sudden drops indicate a module failure
2. **Module reports** — check for FAILED or PARTIAL status
3. **Dead letters** — cases that fail 3+ times are dead-lettered to
   `data/entity-qa/dead_letters.json`

### Adding a Blocklist Entry

When an analyst reports a false positive:

```bash
conda run -n i4g i4g entity-qa blocklist add person "False Positive Name"
```

This edits `config/entity_blocklist.toml`. Deploy the updated config to take effect.

### Tuning Confidence Gates

If a type produces too many false positives, raise its gate:

```toml
# config/settings.default.toml
[extraction]
gate_person = 0.7  # was 0.6
```

Or per-environment via env var: `I4G_EXTRACTION__GATE_PERSON=0.7`.

### Running QA on New Cases

```bash
# Add a case to the bundle
conda run -n i4g i4g entity-qa bundle add-case \
    --bundle regression-v1 \
    --text "Text with entities..." \
    --label '{"person": ["Expected Name"]}'

# Re-score
conda run -n i4g i4g entity-qa score --bundle regression-v1
```

### Adding a New Module

See `copilot/docs/entity-extraction-dev-guide.md` — "Adding a New Extraction Module".

---

## Future Improvements

1. **Entity relationship extraction** — detect directed relationships between entities
2. **Confidence calibration** — use golden bundles to calibrate per-module scores
3. **Active learning loop** — analyst corrections feed back into training data
4. **Module-level caching** — cache regex results for duplicate text submissions
5. **Streaming extraction** — real-time extraction during intake (WebSocket)

---

## Architecture Reference

- [Entity Extraction v2 — Architecture](core/docs/design/entity-extraction-v2.md)
- [Migration Runbook](core/docs/design/entity-extraction-v2-migration.md)
- [Developer Guide](copilot/docs/entity-extraction-dev-guide.md)
