# Bootstrap Local and Dev Environments

Use these recipes to rebuild or verify the local sandbox and the shared dev environment.

## Prepare the required bundles (GCS)
See [Prepare Bootstrap Data Bundles](prepare_bootstrap_bundles.md) for instructions on generating, exporting, and uploading the data bundles required for bootstrapping.

## Local sandbox (I4G_ENV=local)

### Prerequisites
1.  **Conda Environment**: Ensure you are in the `i4g` environment.
2.  **Directory**: Run from the `core/` root.
3.  **Run Date**: Set the `RUN_DATE` environment variable (e.g., `2025-12-17`).

### Bootstrap Command
To fully reset the local sandbox (wipes and rebuilds SQLite, Chroma, OCR artifacts) using the standard 4 data bundles:

```bash
I4G_ENV=local RUN_DATE=2025-12-17 i4g bootstrap local reset \
  --report-dir data/reports/bootstrap_local
```

### Partial Rebuilds
Skip heavy steps if you only need structured/vector data:

```bash
i4g bootstrap local reset --skip-ocr --skip-vector --report-dir data/reports/bootstrap_local
```

### Verification
To verify without regenerating data:

```bash
i4g bootstrap local verify --smoke-search --smoke-dossiers
```

- Flags to know:
  - `--bundle-uri PATH` to stage a specific bundle into `data/bundles/` (in addition to the defaults).
  - `--verify-only` (implied by `verify` command) to emit reports without regenerating data.
  - `--smoke-search` to run the Vertex search smoke; `--smoke-dossiers` (FastAPI running) to verify dossier manifests/signatures.
  - `--force` required if `I4G_ENV` is not `local` (use sparingly).
- After running:
  - Inspect `data/reports/bootstrap_local/` for verification reports:
    - `verify.md`: Human-readable summary of bundles, record counts, and smoke results.
    - `verify.json`: Machine-readable details including file hashes and full smoke outputs.
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
To reset the dev environment by triggering Cloud Run jobs (standard procedure). This will ingest all 4 standard data bundles.

1.  **Set the Run Date**: Identify the date of the bundles you wish to restore (e.g., `2025-12-17`).
    ```bash
    export RUN_DATE="2025-12-17"
    ```

2.  **Run Bootstrap**:
    ```bash
    I4G_ENV=dev i4g bootstrap dev reset \
      --rate-limit-delay 0.5 \
      --run-smoke \
      --run-dossier-smoke \
      --run-search-smoke
    ```

    *   This command triggers multiple Cloud Run jobs (one set per bundle) to rehydrate Firestore, Vertex AI, and BigQuery.
    *   It runs smoke tests immediately after to verify health.
    *   Reports are saved to `data/reports/bootstrap_dev/`.
    *   `--rate-limit-delay 0.5` adds a 0.5s pause between records to respect Vertex AI quotas.

### Verification Only
If you only want to run the smoke tests without rebuilding data:

```bash
I4G_ENV=dev i4g bootstrap dev verify \
  --run-smoke \
  --run-dossier-smoke \
  --run-search-smoke
```

### Verifying Cloud State from Local

You can verify the state of the cloud resources (Cloud SQL, Firestore) from your local machine.

**Important**: The local CLI defaults to SQLite. To verify Cloud SQL, you must explicitly configure the backend and provide credentials via environment variables.

```bash
# Retrieve DB password
DB_PASS=$(gcloud secrets versions access latest --secret="ingest-db-password" --project=i4g-dev)

# Run verification
I4G_ENV=dev \
I4G_STORAGE__STRUCTURED_BACKEND=cloudsql \
I4G_STORAGE__CLOUDSQL_INSTANCE="i4g-dev:us-central1:i4g-dev-db" \
I4G_STORAGE__CLOUDSQL_USER="ingest_user" \
I4G_STORAGE__CLOUDSQL_PASSWORD="$DB_PASS" \
I4G_STORAGE__CLOUDSQL_DATABASE="i4g_db" \
i4g bootstrap dev verify --project i4g-dev --no-run-smoke
```

### Troubleshooting Ingestion

If ingestion jobs fail with `ResourceExhausted` errors (Vertex AI Quota), use the `--rate-limit-delay` flag to throttle the ingestion:

```bash
i4g bootstrap dev reset --project i4g-dev --rate-limit-delay 2.0
```

See [Cloud SQL Primer](cloud_sql_primer.md) for details on inspecting the database directly.

### Debugging: Local Execution
To run the ingestion logic **locally** on your machine but target the Dev environment's infrastructure (Firestore, Vertex AI). This is useful for debugging ingestion logic without waiting for Cloud Run job scheduling or container builds.

> **Note**: This requires your local credentials to have permission to write to Dev Firestore and Vertex AI.

```bash
I4G_ENV=dev RUN_DATE=2025-12-17 i4g bootstrap dev reset \
  --local-execution \
  --rate-limit-delay 0.5
```

### Troubleshooting: IAP Authentication
If you encounter authentication issues with Cloud Run services (e.g., 401/403 errors during smoke tests), you can use the `debug_iap.py` script to verify token generation and audience configuration.

```bash
# Run the debug script
python scripts/debug_iap.py
```

This script checks:
1.  Your current gcloud identity.
2.  Ability to generate ID tokens for the IAP audience.
3.  Connectivity to the `fastapi-gateway` service.

### Job Reference
The bootstrap process orchestrates several Cloud Run Jobs. These jobs are defined in `infra/` (Terraform) and built from `core/docker/`.

| Job Name | Docker Image | Purpose |
| :--- | :--- | :--- |
| `ingest-azure-snapshot` | `ingest-job.Dockerfile` | **Primary Ingestion**: Loads metadata to Firestore, generates embeddings for Vertex AI, syncs SQL/BigQuery. |
| `generate-reports` | `report-job.Dockerfile` | **Reporting**: Generates dossiers and investigation reports. |
| `account-setup` | `account-job.Dockerfile` | **Configuration**: Seeds default saved searches and tag presets. |
| `process-intakes` | `intake-job.Dockerfile` | **Smoke Test**: Processes new intake submissions. |

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
      -d '{"overrides":{"containerOverrides":[{"args":["--bundle-uri=gs://i4g-dev-data-bundles/legacy_azure/$RUN_DATE/","--dataset=legacy_azure_$RUN_DATE"]}]}}'
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
  - Reports (JSON + Markdown) land in `data/reports/bootstrap_dev/` with job status and smoke results. Search smoke is skipped unless both `--search-data-store-id` and `--search-serving-config-id` are provided.
  - **Inspect Outcomes**:
    - Check `data/reports/bootstrap_dev/report.md` for a summary of all job executions and smoke test results.
    - Review `data/reports/bootstrap_dev/report.json` for detailed machine-readable logs, including specific error messages if any step failed.
    - If the intake smoke passed, you can verify the created case in the analyst console or by querying the API directly using the `intake_id` from the logs.

## Data Sources & Design

The bootstrap process uses a frozen snapshot of data captured on **2025-12-17** to ensure consistent environments. These bundles are automatically downloaded from `gs://i4g-dev-data-bundles` during the bootstrap process.

| Bundle | Content | Source |
| :--- | :--- | :--- |
| `legacy_azure` | Historical intake & account artifacts | `legacy_azure/2025-12-17/search_exports/vertex/` |
| `public_scams` | Public datasets (SMS, SpamAssassin) | `public_scams/2025-12-17/cases.jsonl` |
| `retrieval_poc` | Retrieval POC cases | `retrieval_poc/20251217/cases.jsonl` |
| `synthetic_coverage` | Synthetic coverage cases | `synthetic_coverage/2025-12-17/full/cases.jsonl` |

For full inventory, licensing, and synthetic scope details, see [Bundle Sources and Synthetic Coverage](../development/bundle_sources_and_coverage.md).

### Maintenance Notes
- **Do not hand-edit `data/`**: Rerun `i4g bootstrap local reset` to restore the baseline.
- **Configuration**: Keep `config/settings.local.toml` aligned when overriding paths and regenerate manifests with `scripts/export_settings_manifest.py` if needed.
