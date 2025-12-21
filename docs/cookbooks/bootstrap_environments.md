# Bootstrap Local and Dev Environments

Use these recipes to rebuild or verify the local sandbox and the shared dev environment.

## Prepare the required bundles (GCS)
See [Prepare Bootstrap Data Bundles](prepare_bootstrap_bundles.md) for instructions on generating, exporting, and uploading the data bundles required for bootstrapping.

## Local sandbox (I4G_ENV=local)

### Prerequisites
1.  **Conda Environment**: Ensure you are in the `i4g` environment.
2.  **Directory**: Run from the `core/` root.
3.  **Run Date**: Set the `RUN_DATE` environment variable (e.g., `2025-01-01`).

### Bootstrap Command
To fully reset the local sandbox (wipes and rebuilds SQLite, Chroma, OCR artifacts):

```bash
I4G_ENV=local i4g bootstrap local reset \
  --bundle-uri gs://i4g-dev-data-bundles/legacy_azure/$RUN_DATE/manifest.generated.json \
  --report-dir data/reports/local_bootstrap
```

### Partial Rebuilds
Skip heavy steps if you only need structured/vector data:

```bash
i4g bootstrap local reset --skip-ocr --skip-vector --report-dir data/reports/local_bootstrap
```

### Verification
To verify without regenerating data:

```bash
i4g bootstrap local reset --verify-only --smoke-search --smoke-dossiers
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

### Prerequisites
1.  **GCloud Auth**: You must be authenticated with `gcloud` and have access to the `i4g-dev` project.
    ```bash
    gcloud auth login
    gcloud auth application-default login
    gcloud config set project i4g-dev
    ```
2.  **Impersonation**: You need to impersonate the infra service account for Bootstrap operations.
    ```bash
    gcloud config set auth/impersonate_service_account sa-infra@i4g-dev.iam.gserviceaccount.com
    ```

### Bootstrap Command
To reset the dev environment by triggering Cloud Run jobs (standard procedure):

1.  **Set the Run Date**: Identify the date of the legacy Azure bundle you wish to restore (e.g., `2025-01-01`).
    ```bash
    export RUN_DATE="2025-01-01"
    ```

2.  **Run Bootstrap**:
    ```bash
    I4G_ENV=dev i4g bootstrap dev reset \
      --bundle-uri gs://i4g-dev-data-bundles/legacy_azure/$RUN_DATE/manifest.generated.json \
      --dataset legacy_azure_$RUN_DATE \
      --run-smoke \
      --run-dossier-smoke \
      --run-search-smoke
    ```

    *   This command triggers Cloud Run jobs to rehydrate Firestore, Vertex AI, and BigQuery.
    *   It runs smoke tests immediately after to verify health.
    *   Reports are saved to `data/reports/dev_bootstrap/`.

### Verification Only
If you only want to run the smoke tests without rebuilding data:

```bash
I4G_ENV=dev i4g bootstrap dev verify \
  --run-smoke \
  --run-dossier-smoke \
  --run-search-smoke
```

### Debugging: Local Execution
To run the ingestion logic **locally** on your machine but target the Dev environment's infrastructure (Firestore, Vertex AI). This is useful for debugging ingestion logic without waiting for Cloud Run job scheduling or container builds.

> **Note**: This requires your local credentials to have permission to write to Dev Firestore and Vertex AI.

```bash
I4G_ENV=dev i4g bootstrap dev reset \
  --local-execution \
  --bundle-uri gs://i4g-dev-data-bundles/legacy_azure/$RUN_DATE/manifest.generated.json \
  --dataset legacy_azure_$RUN_DATE \
  --run-smoke
```

### Job Reference
The bootstrap process orchestrates several Cloud Run Jobs. These jobs are defined in `infra/` (Terraform) and built from `core/docker/`.

| Job Name | Docker Image | Purpose |
| :--- | :--- | :--- |
| `bootstrap-firestore` | `ingest-job.Dockerfile` | Loads case metadata into Firestore. |
| `bootstrap-vertex` | `ingest-job.Dockerfile` | Generates embeddings and upserts to Vertex AI Search. |
| `bootstrap-sql` | `ingest-job.Dockerfile` | Writes structured data to Cloud SQL (Postgres). |
| `bootstrap-bigquery` | `ingest-job.Dockerfile` | Loads analytics data into BigQuery. |
| `bootstrap-reports` | `report-job.Dockerfile` | Generates dossiers and investigation reports. |
| `bootstrap-saved-searches` | `account-job.Dockerfile` | Seeds default saved searches and tag presets. |
| `process-intakes` | `intake-job.Dockerfile` | Processes new intake submissions (used in smoke tests). |

> **Note**: The `ingest-job` image is versatile and handles multiple backends (Firestore, Vertex, SQL) based on environment variables passed by the job definition.

### Troubleshooting
If you encounter issues with `gcloud` versions or job execution failures, see the [Troubleshooting Guide](#troubleshooting-bootstrap).

## Troubleshooting Bootstrap

### Manual Job Execution (GCloud Fallback)
If `gcloud run jobs execute` fails with `Unknown name "delayExecution" at 'overrides'` (seen in gcloud 550.0.0), either downgrade gcloud (e.g., 549.0.0) or call the Cloud Run Jobs API directly.

1.  **List Jobs**:
    ```bash
    gcloud run jobs list --project i4g-dev --region us-central1 --format='table(name)'
    # Example: ingest-azure-snapshot, generate-reports, process-intakes
    ```

2.  **Execute via API**:
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

### Finding Vertex Data Store ID
If you need to manually find the Vertex data store ID:

```bash
ACCESS_TOKEN=$(gcloud auth print-access-token)
curl -s \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "X-Goog-User-Project: i4g-dev" \
  "https://discoveryengine.googleapis.com/v1/projects/i4g-dev/locations/global/collections/default_collection/dataStores" \
  | jq -r '.dataStores[]? | "\(.name|split("/")[-1])\t\(.displayName)"'
```
Dev default: `retrieval-poc` with serving config `default_search`.

- Guardrails and outputs:
  - Blocks prod-like projects unless `--force` and warns if `I4G_ENV` is not `dev`/`local`.
  - Logs bundle URI and sha256 when `--bundle-uri` points to a local file; pass `--dataset` and `--bundle-uri` so every job sees the same inputs.
  - Reports (JSON + Markdown) land in `data/reports/dev_bootstrap/` with job status and smoke results. Search smoke is skipped unless both `--search-data-store-id` and `--search-serving-config-id` are provided.
  - **Inspect Outcomes**:
    - Check `data/reports/dev_bootstrap/dev_bootstrap_report.md` for a summary of all job executions and smoke test results.
    - Review `data/reports/dev_bootstrap/dev_bootstrap_report.json` for detailed machine-readable logs, including specific error messages if any step failed.
    - If the intake smoke passed, you can verify the created case in the analyst console or by querying the API directly using the `intake_id` from the logs.

## Notes and further reading
- Avoid hand-editing `data/`; rerun the bootstrap scripts for reproducibility. Keep `config/settings.local.toml` aligned when overriding paths and regenerate manifests with `scripts/export_settings_manifest.py` if needed.
- Design/background: see [Bundle Sources and Synthetic Coverage](../development/bundle_sources_and_coverage.md) for source inventory, licensing, and synthetic coverage scope.
