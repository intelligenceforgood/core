# synthetic_thefts — Synthetic Test Fixtures

This directory contains minimal synthetic data for testing Phase D of the PhishDestroy Sprint 2
archive ingestion pipeline. It is **not** real threat intelligence.

## Purpose

Exercises `_ingest_successful_thefts()` and `parse_deposit_messages()` end-to-end via
`SyntheticTheftsAdapter` in `test_archive_damage_integration.py`.

## Files

| File | Description |
|------|-------------|
| `iocs.json` | Minimal team metadata. `panel_url` set to an unresolvable test domain. |
| `successful_thefts/result.json` | 5 messages: 2 valid RU format, 1 valid EN format, 1 service (skipped), 1 no-header (skipped). |

## Message Details

- Message 101: RU format, $500 USD, BSC chain, TrustWallet project
- Message 102: RU format via text_entities, $1200.50 USD, ETH chain, MetaMask project
- Message 103: EN format, $750 USD, SOL chain, PhantomWallet project
- Message 104: service type → skipped
- Message 105: no deposit header → skipped
