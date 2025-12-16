# Bootstrap Local and Dev Environments

Use these recipes to rebuild or verify the local sandbox and the shared dev environment.

## Local sandbox (I4G_ENV=local)
- Prereqs: Conda env `i4g`; run from repo root `core/`.
- Full reset (wipes and rebuilds SQLite, Chroma, OCR artifacts, pilot cases):
  ```bash
  conda run -n i4g python scripts/bootstrap_local_sandbox.py --reset
  ```
- Partial rebuilds: skip heavy pieces when you only need structured/vector data or OCR artifacts:
  ```bash
  conda run -n i4g python scripts/bootstrap_local_sandbox.py --reset --skip-ocr --skip-vector
  ```
- Flags to know:
  - `--bundle-uri PATH` to stage a specific bundle into `data/bundles/`.
  - `--verify-only` to emit reports without regenerating data.
  - `--smoke-search` to run the Vertex search smoke; `--smoke-dossiers` (FastAPI running) to verify dossier manifests/signatures.
  - `--force` required if `I4G_ENV` is not `local` (use sparingly).
- After running:
  - Inspect `data/reports/local_bootstrap/` for JSON/Markdown reports (bundle hashes, manifest sha256, ingestion-run summary, smokes).
  - Point ingestion/search to the refreshed dataset (`ingestion.default_dataset`).
  - Run a quick smoke: [docs/cookbooks/smoke_test.md](docs/cookbooks/smoke_test.md).

## Dev environment (I4G_ENV=dev)
- Prereqs: Auth to the dev project; WIF SA typically `sa-infra@i4g-dev.iam.gserviceaccount.com`.
- Dry-run first to confirm job args:
  ```bash
  conda run -n i4g python scripts/bootstrap_dev_env.py \
    --project i4g-dev --region us-central1 --dry-run
  ```
- Execute Cloud Run jobs (Firestore, Vertex, SQL, BigQuery, GCS assets, reports, saved searches):
  ```bash
  conda run -n i4g python scripts/bootstrap_dev_env.py \
    --project i4g-dev --region us-central1 \
    --bundle-uri gs://i4g-dev-data-bundles/demo/bundle.jsonl \
    --run-smoke --run-dossier-smoke --run-search-smoke
  ```
- Guardrails:
  - Blocks prod-like projects unless `--force` is set; warns when forcing.
  - Logs bundle URI and sha256 (for local file URIs) before running jobs.
  - Use `--verify-only` to run smokes without executing jobs.
- Outputs: reports land in `data/reports/dev_bootstrap/` (JSON + Markdown with job statuses and smokes).

## Notes and further reading
- Avoid hand-editing `data/`; rerun the bootstrap scripts for reproducibility. Keep `config/settings.local.toml` aligned when overriding paths and regenerate manifests with `scripts/export_settings_manifest.py` if needed.
- Design/background: see [docs/bundle_sources_and_coverage.md](docs/bundle_sources_and_coverage.md) for source inventory, licensing, and synthetic coverage scope.
