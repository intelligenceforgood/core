# Bundle Sources and Synthetic Coverage (Reference)

This page captures the durable reference for what goes into our bootstrap bundles and why. Use it when preparing or
reviewing local/dev refreshes.

## Source inventory
- Legacy Azure exports: historical intake, GroupsIO, and account artifacts pulled from Azure SQL/blob. Preserve schema
  maps and row counts in the bundle manifest; ensure PII handling follows core/docs/pii_vault.md before promotion.
- Public/third-party datasets (candidates):
  - UCI SMS Spam Collection (CC BY-NC 4.0) — already included in legacy bundle.
  - SpamAssassin corpus (Apache-style) — email spam/ham; confirm terms before shipping.
  - CSIC 2010 HTTP (CC BY 4.0) — benign/attack traffic, useful for anomalies.
  - CryptoScamDB archive — permissive license likely; verify before inclusion.
  - PhishTank/OpenPhish, BitcoinAbuse — require TOS/legal review before bundling.
- PII and licensing: only include data with clear redistribution terms; keep canonical bundles in restricted GCS with
  versioning and lifecycle.

## Synthetic coverage set (scope)
- Objectives: exercise ingestion → storage → indexing → retrieval with ground truth for verification.
- Shape: ~150–250 records full bundle; ~20–30 smoke slice. Categories span crypto wallet verification, romance/investment
  pretexts, tech support, gov impostor, payment-handle redirects, and mule/bank redirects.
- Record fields: id/source/text/platform/scam_type/confidence, entities (wallets, banks, payment handles), structured
  fields, tags; optional OCR-like text for a subset.
- Artifacts to emit:
  - `synthetic_cases.jsonl` (primary records)
  - `synthetic_cases_ground_truth.yaml` (labels/entities/tags)
  - `vertex_docs.jsonl` (Vertex-ready docs)
  - `saved_searches.json` (tag presets / saved searches)
  - `ocr_samples/` (text or renders) with extraction ground truth
  - Manifest with hashes/counts for all artifacts
- Sizing: full bundle a few GB across all sources; smoke slice <50 MB, PII-free where possible.

## Placement and manifests
- Author locally under `data/bundles/` (gitignored), then publish to the versioned bucket `gs://i4g-dev-data-bundles/{bundle_id}/`.
- Provide a small smoke slice for CI/manual smokes; keep PII-free.
- Every bundle ships a manifest with file inventory, hashes, counts, provenance, license notes, PII flags, and
  ingestion-run/log counts when applicable.

## Maintenance checklist
- Confirm licenses/TOS before adding public data; record terms in the manifest.
- Keep manifests and hashes up to date when regenerating synthetic artifacts.
- When promoting a bundle to GCS, ensure versioning and IAM are in place; avoid Drive mirrors for canonical copies.
- Align saved searches/tag presets with the synthetic categories so verification smokes remain meaningful.
