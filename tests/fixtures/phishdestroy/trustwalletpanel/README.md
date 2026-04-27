# TrustWalletPanel Test Fixtures

These are hand-trimmed, minimal fixture files for the TrustWalletPanel golden contract test
(`tests/unit/ingestion/test_archive_trustwalletpanel.py`).

**Upstream source:** `phishdestroy/ScamIntelLogs/TrustWalletPanel/`
**Upstream commit:** `83d0307420fcc865fcb8a34b8c454acbc6d56f1f`

## Deliberate truncations

- `iocs.json`: Retains only the top-level keys consumed by Phase B (`team`, `type`, `first_seen`,
  `last_activity`, `panel_url`, `tech_stack`). Large nested blocks (`operator_identities`,
  `telegram_actors`, `financial_damage`, etc.) are replaced with empty objects `{}`.
- `chats_translated.json`: Contains exactly **3 chat-session entries** (ids 7, 92, 446) with 2–4
  messages each, hand-authored to exercise the fixture contract:
  - Entry 7: admin messages contain "deposit" → `deposit_demand=True`
  - Entry 92: admin messages contain "OFAC" and "replacement" → `deposit_demand=True`
  - Entry 446: no deposit/OFAC keywords → `deposit_demand=False`

## Do not re-export

These files are derived from confidential scam-intelligence research. Do not copy, publish, or
distribute them outside the `core/tests/fixtures/` directory. Full upstream data must not be
committed to this repository.
