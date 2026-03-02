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
To fully reset the local sandbox (wipes and rebuilds structured DB, Chroma, OCR artifacts) using the standard 4 data bundles:

```bash
RUN_DATE=2025-12-17 \
I4G_ENV=local \
i4g bootstrap local reset
```

### Partial Rebuilds
Skip heavy steps if you only need structured/vector data:

```bash
i4g bootstrap local reset --skip-ocr --skip-vector
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
3.  **PII Pepper**: For verification commands to work locally (which verify remote jobs), you must export the tokenization pepper.
    ```bash
    # Fetch from Secret Manager if you have access, or ask an admin
    export I4G_PII__PEPPER=$(gcloud secrets versions access latest --secret="tokenization-pepper" --project="i4g-dev")
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
      --timeout 10800 \
      --run-smoke \
      --run-dossier-smoke \
      --run-search-smoke
    ```

    *   This command triggers multiple Cloud Run jobs (one set per bundle) to rehydrate Cloud SQL, Vertex AI, and BigQuery.
    *   It runs smoke tests immediately after to verify health.
    *   Reports are saved to `data/reports/bootstrap_dev/`.
    *   `--rate-limit-delay 0.5` adds a 0.5s pause between records to respect Vertex AI quotas.

### Verification Only
If you only want to run the smoke tests without rebuilding data. **Note:** This requires `I4G_PII__PEPPER` to be set in your local environment so the local runner can inject it into the verification logic.

```bash
export I4G_PII__PEPPER=$(gcloud secrets versions access latest --secret="tokenization-pepper" --project="i4g-dev")

I4G_ENV=dev i4g bootstrap dev verify \
  --run-smoke \
  --run-dossier-smoke \
  --run-search-smoke
```

### Debugging: Local Execution
To run the ingestion logic **locally** on your machine but target the Dev environment's infrastructure (Cloud SQL, Vertex AI). This is useful for debugging ingestion logic without waiting for Cloud Run job scheduling or container builds.

> **Note**: This requires your local credentials to have permission to write to Dev Cloud SQL and Vertex AI.

```bash
I4G_ENV=dev RUN_DATE=2025-12-17 i4g bootstrap dev reset \
  --local-execution \
  --rate-limit-delay 0.5
```

### Fast Testing / Debugging
To test specific bootstrap steps without running the full pipeline (which can take hours):

**1. Test OCR Extraction Only:**
Target the `ocr_test_images` bundle and skip other steps.
```bash
i4g bootstrap dev --bundle ocr_test_images --skip-reports --skip-saved-searches
```

**2. Test Review Seeding Only:**
Skip all ingestion steps to run just the review seeding job.
```bash
i4g bootstrap dev \
  --skip-vertex --skip-sql --skip-bigquery --skip-gcs-assets \
  --skip-reports --skip-saved-searches
```

**3. Dry Run Ingestion (No DB Writes):**
Run the full ingestion pipeline (including OCR and classification) but skip writing to Cloud SQL/Vertex. Useful for debugging extraction crashes or rate limits.
```bash
i4g bootstrap dev reset --bundle ocr_test_images --ingest-dry-run
```

**4. Test Review Seeding Locally:**
Run the seeding logic directly on your machine (requires dev credentials).
```bash
I4G_ENV=dev i4g admin seed-reviews
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
3.  Connectivity to the `core-svc` service.

### Job Reference
The bootstrap process orchestrates several Cloud Run Jobs. These jobs are defined in `infra/` (Terraform) and built from `core/docker/`.

| Job Name | Docker Image | Purpose |
| :--- | :--- | :--- |
| `ingest-bootstrap` | `ingest-job.Dockerfile` | **Primary Ingestion**: Loads metadata to Cloud SQL, generates embeddings for Vertex AI, syncs SQL/BigQuery. |
| `generate-reports` | `report-job.Dockerfile` | **Reporting**: Generates dossiers and investigation reports. Also used for **Review Seeding** (via `seed-reviews` command override). |
| `account-setup` | `account-job.Dockerfile` | **Configuration**: Seeds default saved searches and tag presets. |
| `process-intakes` | `intake-job.Dockerfile` | **Smoke Test**: Processes new intake submissions. |

> **Note**: The `ingest-job` image is versatile and handles multiple backends (Cloud SQL, Vertex) based on environment variables passed by the job definition.

## Data Sources & Design

The bootstrap process uses a frozen snapshot of data captured on **2025-12-17** to ensure consistent environments. These bundles are automatically downloaded from `gs://i4g-dev-data-bundles` during the bootstrap process.

For full inventory, licensing, and synthetic scope details, see [Bundle Sources and Synthetic Coverage](../development/bundle_sources_and_coverage.md).

### Maintenance Notes
- **Do not hand-edit `data/`**: Rerun `i4g bootstrap local reset` to restore the baseline.
- **Configuration**: Keep `config/settings.local.toml` aligned when overriding paths and regenerate manifests with `scripts/export_settings_manifest.py` if needed.
