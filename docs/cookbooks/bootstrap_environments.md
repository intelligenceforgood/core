# Bootstrap Local and Dev Environments

Use these recipes to rebuild or verify the local sandbox and the shared dev environment.

## Local sandbox (I4G_ENV=local)
- Prereqs: Conda env `i4g`; run from repo root `core/`.
  - Full reset (wipes and rebuilds SQLite, Chroma, OCR artifacts, pilot cases):
    ```bash
    I4G_ENV=local i4g bootstrap local reset \
      --bundle-uri gs://i4g-dev-data-bundles/legacy_azure/$RUN_DATE/manifest.generated.json \
      --report-dir data/reports/local_bootstrap
    ```
  - The above command replays the legacy Azure bundle you exported; set `RUN_DATE` first so the `bundle-uri` matches the folder you uploaded in the bundle prep section. The bundle-manifest step writes `manifest.generated.json` into the upload, and that is the canonical manifest the bootstrap helper stages before rebuilding bag.
- Partial rebuilds: skip heavy pieces when you only need structured/vector data or OCR artifacts:
  ```bash
  i4g bootstrap local reset --skip-ocr --skip-vector --report-dir data/reports/local_bootstrap
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
- Prereqs: export `I4G_ENV=dev`; impersonate `sa-infra@i4g-dev.iam.gserviceaccount.com` (WIF) via `gcloud auth application-default login` plus `--impersonate-service-account`; set the gcloud project to `i4g-dev`.
- Dry-run the Cloud Run plan before touching data:
  ```bash
  I4G_ENV=dev i4g bootstrap dev reset \
    --project i4g-dev --region us-central1 \
    --bundle-uri gs://i4g-dev-data-bundles/legacy_azure/$RUN_DATE/manifest.generated.json \
    --dataset legacy_azure_$RUN_DATE \
    --dry-run \
    --report-dir data/reports/dev_bootstrap
  ```
  - Run the bootstrap jobs with smokes (intake, dossier, search):
  ```bash
  I4G_ENV=dev i4g bootstrap dev reset \
    --project i4g-dev --region us-central1 \
    --bundle-uri gs://i4g-dev-data-bundles/legacy_azure/$RUN_DATE/manifest.generated.json \
    --dataset legacy_azure_$RUN_DATE \
    --run-smoke \
    --run-dossier-smoke \
    --run-search-smoke \
    --search-data-store-id retrieval-poc \
    --search-serving-config-id default_search \
    --report-dir data/reports/dev_bootstrap
  ```
    - Default Cloud Run jobs (if deployed): `bootstrap-firestore`, `bootstrap-vertex`, `bootstrap-sql`, `bootstrap-bigquery`, `bootstrap-gcs-assets`, `bootstrap-reports`, `bootstrap-saved-searches`. If you see a 404 for a job, list what exists and override with the deployed names:
      ```bash
      gcloud run jobs list --project i4g-dev --region us-central1 --format='table(name)'
      # Example current dev jobs: account-list, dossier-queue, generate-reports, ingest-azure-snapshot,
      # ingest-network-smoke, process-intakes (legacy Azure system is shut down; use the existing bundle only)
      ```
      Then set `JOB` to one of the listed names when using the curl fallback below.
  - Find the Vertex data store id in dev. If your gcloud build lacks the `discovery-engine` group, call the API directly with ADC and a quota project header:
    ```bash
    ACCESS_TOKEN=$(gcloud auth print-access-token)
    curl -s \
      -H "Authorization: Bearer $ACCESS_TOKEN" \
      -H "X-Goog-User-Project: i4g-dev" \
      "https://discoveryengine.googleapis.com/v1/projects/i4g-dev/locations/global/collections/default_collection/dataStores" \
      | jq -r '.dataStores[]? | "\(.name|split("/")[-1])\t\(.displayName)"'
    ```
    The first column is the `data_store_id`; pass it to `--search-data-store-id`. Dev default: `retrieval-poc` with serving config `default_search` in location `global`.
    - If you see a quota-project warning with ADC, run `gcloud auth application-default set-quota-project i4g-dev` and retry. Discovery Engine is already enabled for the project via `infra/environments/app/dev` Terraform.
    - If `gcloud run jobs execute` fails with `Unknown name "delayExecution" at 'overrides'` (seen in gcloud 550.0.0), either downgrade gcloud (e.g., 549.0.0) or call the Cloud Run Jobs API directly. Ensure `JOB` matches an existing job from the list above (a 404 means the job is not deployed):
      ```bash
      ACCESS_TOKEN=$(gcloud auth print-access-token --impersonate-service-account sa-infra@i4g-dev.iam.gserviceaccount.com)
      JOB=ingest-azure-snapshot
      curl -s -X POST \
        -H "Authorization: Bearer $ACCESS_TOKEN" \
        -H "X-Goog-User-Project: i4g-dev" \
        -H "Content-Type: application/json" \
        "https://run.googleapis.com/v2/projects/i4g-dev/locations/us-central1/jobs/$JOB:run" \
        -d '{"overrides":{"containerOverrides":[{"args":["--bundle-uri=gs://i4g-dev-data-bundles/legacy_azure/$RUN_DATE/manifest.generated.json","--dataset=legacy_azure_$RUN_DATE"]}]}}'
      ```
      Replace `JOB` per target; use `generate-reports` for dossier/report rebuilds and `process-intakes` for intake smoke. Azure weekly refresh is retired; bootstrap consumes the existing bundle in `gs://i4g-dev-data-bundles/legacy_azure` (no upstream Azure pulls).
  - Verification-only (no job execution, smokes only):
  ```bash
  I4G_ENV=dev i4g bootstrap dev verify \
    --project i4g-dev --region us-central1 \
    --run-smoke --run-dossier-smoke --run-search-smoke \
    --search-data-store-id retrieval-poc \
    --search-serving-config-id default_search \
    --report-dir data/reports/dev_bootstrap
  ```
    - **Note**: The dev FastAPI service is behind IAP. The bootstrap tool automatically fetches your local `gcloud` identity token to authenticate. Ensure you have run `gcloud auth login` and have access to the IAP-protected application.
    - **Note on Dossier Smoke**: You may see `Dossier smoke failed: No dossiers returned` if the environment is fresh. This is expected because the verification command only submits an intake (creating a case) but does not trigger the full report generation workflow that populates the dossier queue. To populate dossiers, run the full reset command or manually trigger report generation.

- Guardrails and outputs:
  - Blocks prod-like projects unless `--force` and warns if `I4G_ENV` is not `dev`/`local`.
  - Logs bundle URI and sha256 when `--bundle-uri` points to a local file; pass `--dataset` and `--bundle-uri` so every job sees the same inputs.
  - Reports (JSON + Markdown) land in `data/reports/dev_bootstrap/` with job status and smoke results. Search smoke is skipped unless both `--search-data-store-id` and `--search-serving-config-id` are provided.
  - **Inspect Outcomes**:
    - Check `data/reports/dev_bootstrap/dev_bootstrap_report.md` for a summary of all job executions and smoke test results.
    - Review `data/reports/dev_bootstrap/dev_bootstrap_report.json` for detailed machine-readable logs, including specific error messages if any step failed.
    - If the intake smoke passed, you can verify the created case in the analyst console or by querying the API directly using the `intake_id` from the logs.

## Prepare the required bundles (GCS)
See [Prepare Bootstrap Data Bundles](prepare_bootstrap_bundles.md) for instructions on generating, exporting, and uploading the data bundles required for bootstrapping.

## Notes and further reading
- Avoid hand-editing `data/`; rerun the bootstrap scripts for reproducibility. Keep `config/settings.local.toml` aligned when overriding paths and regenerate manifests with `scripts/export_settings_manifest.py` if needed.
- Design/background: see [Bundle Sources and Synthetic Coverage](../development/bundle_sources_and_coverage.md) for source inventory, licensing, and synthetic coverage scope.
