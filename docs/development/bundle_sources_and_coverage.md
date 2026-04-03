# Bundle Sources and Synthetic Coverage

This page captures the durable reference for what goes into our bootstrap bundles and why. Use it when preparing or
reviewing local/dev refreshes.

## Source inventory

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
  - `cases.jsonl` (primary records, standardized schema)
  - `ocr_test_images/` (synthetic chat screenshots for OCR testing)
  - `ground_truth.yaml` (optional labels/entities for verification)
  - Manifest with hashes/counts for all artifacts
- Sizing: full bundle a few GB across all sources; smoke slice <50 MB, PII-free where possible.

## Current Snapshot (2025-12-17)

The current bootstrap process relies on a frozen snapshot of data stored in `gs://i4g-dev-data-bundles/2025-12-17/`.

| Bundle Key           | Description                                             | GCS Path (Relative to Run Date)                |
| :------------------- | :------------------------------------------------------ | :--------------------------------------------- |
| `public_scams`       | Public datasets (SMS Spam Collection, SpamAssassin).    | `public_scams/cases.jsonl`                     |
| `retrieval_poc`      | Small subset of synthetic cases for retrieval testing.  | `synthetic_coverage/retrieval_poc/cases.jsonl` |
| `synthetic_coverage` | Full set of synthetic cases for broad coverage testing. | `synthetic_coverage/full/cases.jsonl`          |
| `ocr_test_images`    | Synthetic chat screenshots for OCR pipeline testing.    | `synthetic_coverage/ocr_test_images/`          |

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
