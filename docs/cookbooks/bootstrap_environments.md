# Bootstrap Local and Dev Environments

Use these recipes to rebuild or verify the local sandbox and the shared dev environment.

## Prepare the required bundles (GCS)

See [Prepare Bootstrap Data Bundles](prepare_bootstrap_bundles.md) for instructions on generating, exporting, and uploading the data bundles required for bootstrapping.

## Golden Data Bundle

The golden bundle consolidates all data sources into a single, quality-filtered package:

- **Cleaned legacy Azure** cases (min 50-char text, deduped by SHA-256)
- **Public scam** corpora (kept as-is)
- **Incident report responses** (Google Sheet CSV → JSONL ETL)
- **Synthetic coverage** cases (minus OCR test images and low-quality records)
- **Seed SQL** — direct DB inserts for campaigns, watchlists, graph edges, review queue, and geographic data

To build the golden bundle locally:

```bash
# Run ETL scripts first (from core/ root)
python scripts/etl/clean_legacy_azure.py --input data/bundles/legacy_azure --output data/bundles/legacy_azure_clean/cases.jsonl
python scripts/etl/etl_incident_responses.py --csv data/exports/incident_responses.csv --output data/bundles/incident_responses/cases.jsonl
python scripts/etl/synthesize_golden_data.py --output data/bundles/golden_seed/seed.sql

# Build the consolidated bundle
i4g bootstrap build-golden-bundle --bundles-dir data/bundles --output-dir data/bundles/golden
```

The golden bundle produces:

- `cases.jsonl` — consolidated case data for the ingestion pipeline
- `seed.sql` — campaigns, watchlists, graph edges, timeline data, geography
- `manifest.json` — provenance, counts, SHA-256 hashes

## Two-Phase Ingestion (Fast Ingest → Async Classify)

Bootstrap uses a two-phase approach for speed:

1. **Fast ingest** — cases are written to SQL/Vertex with `classification_status = 'pending'` (no LLM calls)
2. **Async classify** — the `classification_sweeper` Cloud Run job runs every 5 minutes, picks up pending cases, and classifies them via Gemini

This decouples the expensive LLM classification from bulk data loading. The sweeper is already scheduled in Cloud Scheduler (`*/5 * * * *`). To trigger it manually:

```bash
i4g jobs run classification-sweeper
```

The `analytics_aggregation` job updates entity/indicator/campaign stats every 4 hours (`0 */4 * * *`).

## Database Management

### Wipe

```bash
# Local — deletes SQLite, Chroma, reports, manual demo
i4g db wipe --env local

# Dev — TRUNCATE all data tables in Cloud SQL (preserves schema + accounts)
i4g db wipe --env dev --confirm "yes-wipe-dev"
```

The wipe command supports `--dry-run` to preview which tables would be affected.

### Backup

```bash
# Local — creates timestamped tar.gz archive
i4g db backup --env local

# Dev — pg_dump via Cloud SQL Auth Proxy
i4g db backup --env dev
```

### Restore

```bash
# Local — extract archive to data/
i4g db restore --env local --from data/backups/backup_local_20250115_120000.tar.gz

# Dev — pg_restore via Cloud SQL Auth Proxy
i4g db restore --env dev --from gs://i4g-dev-data-bundles/backups/20250115/dump.sql.gz --confirm
```

## Local sandbox (I4G_ENV=local)

### Prerequisites

1.  **Conda Environment**: Ensure you are in the `i4g` environment.
2.  **Directory**: Run from the `core/` root.
3.  **Run Date**: Set the `RUN_DATE` environment variable (e.g., `2025-12-17`).

### Bootstrap Command

To fully reset the local sandbox (wipes and rebuilds structured DB, Chroma, OCR artifacts):

```bash
# Using legacy bundles (default)
RUN_DATE=2025-12-17 I4G_ENV=local i4g bootstrap local reset

# Using golden bundle
I4G_BOOTSTRAP__USE_GOLDEN_BUNDLE=true I4G_ENV=local i4g bootstrap local reset
```

The local bootstrap flow:

1. Reset artifacts (delete SQLite, Chroma, reports)
2. Apply Alembic migrations
3. Seed campaigns
4. Ingest JSONL bundles (skip-classification is always on for local)
5. **Apply seed SQL** from golden bundle (campaigns, watchlists, graph, timeline, geography)
6. OCR processing (if Tesseract available)
7. Rebuild manual demo
8. Seed review cases
9. Verify sandbox

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
  - Inspect `data/reports/bootstrap_local/` for verification reports.
  - Point ingestion/search to the refreshed dataset (`ingestion.default_dataset`).

### Post-Bootstrap: Backfill Processing

After bootstrap, many cases have `classification_status='pending'` and need async processing (classification, risk scoring, SSI investigation, analytics). Use the **backfill framework** to process them:

```bash
# Check what needs processing
I4G_ENV=local i4g backfill status

# Run all backfill tasks once
I4G_ENV=local i4g backfill run all

# Or launch the daemon (continuous loop — fire and forget)
I4G_ENV=local nohup i4g backfill daemon --cycle 60 > data/logs/backfill.log 2>&1 &

# Monitor progress
tail -f data/logs/backfill.log
I4G_ENV=local i4g backfill status
```

The daemon cycles through all registered tasks (classify, SSI, analytics, linkage, evidence, etc.), processing pending items until the queue is empty, then sleeping between cycles. It is **reentrant** — safe to restart at any time; it picks up where it left off.

#### SSI Configuration (Local)

The `ssi` backfill task triggers auto-investigations for uninvestigated URL indicators. In local mode, this requires the SSI dev server running alongside core. Enable it in `config/settings.local.toml`:

```toml
[auto_investigate]
enabled = true
max_concurrent = 3
staleness_days = 30

[ssi]
service_url = "http://localhost:8100"
```

Then start the SSI service in a separate terminal:

```bash
cd ../ssi
conda run -n i4g-ssi uvicorn ssi.api.app:app --reload --port 8100
```

No OIDC token is needed locally — auth falls back gracefully when the token fetch fails.

See [Backfill Framework Runbook](backfill_framework.md) for full CLI reference, concurrency details, and troubleshooting.

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

To reset the dev environment by triggering Cloud Run jobs. Classification is skipped by default (two-phase approach):

```bash
I4G_ENV=dev i4g bootstrap dev reset \
  --rate-limit-delay 0.5 \
  --timeout 10800 \
  --run-smoke \
  --run-dossier-smoke \
  --run-search-smoke
```

To enable inline classification during ingest (slower):

```bash
I4G_ENV=dev i4g bootstrap dev reset --no-skip-classification ...
```

### Verification Only

If you only want to run the smoke tests without rebuilding data:

```bash
I4G_ENV=dev i4g bootstrap dev verify \
  --run-smoke \
  --run-dossier-smoke \
  --run-search-smoke
```

### Debugging: Local Execution

To run the ingestion logic **locally** but target the Dev environment's infrastructure:

```bash
I4G_ENV=dev RUN_DATE=2025-12-17 i4g bootstrap dev reset \
  --local-execution \
  --rate-limit-delay 0.5
```

### Fast Testing / Debugging

**Test specific bundles:**

```bash
i4g bootstrap dev --bundle ocr_test_images --skip-reports --skip-saved-searches
```

**Dry run ingestion (no DB writes):**

```bash
i4g bootstrap dev reset --bundle ocr_test_images --ingest-dry-run
```

### Job Reference

| Job Name           | Docker Image            | Purpose                                           |
| :----------------- | :---------------------- | :------------------------------------------------ |
| `ingest-bootstrap` | `ingest-job.Dockerfile` | Primary ingestion: Cloud SQL, Vertex AI, BigQuery |
| `generate-reports` | `report-job.Dockerfile` | Dossiers, reports, review seeding                 |
| `process-intakes`  | `intake-job.Dockerfile` | Smoke test: processes new intake submissions      |

### Post-Bootstrap: Backfill Processing (Dev)

> **How environment targeting works:** The `i4g backfill` CLI does not have an `--env` flag. It reads `I4G_ENV` and the corresponding `I4G_*` env vars to determine which database and services to connect to — same pattern as `i4g jobs run`.

#### Steady-state (already handled)

In dev, Cloud Scheduler already triggers the individual Cloud Run jobs that backfill wraps:

| Job                      | Schedule       | Cloud Run Image |
| :----------------------- | :------------- | :-------------- |
| `classification_sweeper` | `*/5 * * * *`  | `core-svc`      |
| `analytics_aggregation`  | `0 */4 * * *`  | `core-svc`      |
| `auto_investigate`       | `*/10 * * * *` | `core-svc`      |

These jobs already process pending work continuously. You only need the backfill CLI for **post-bootstrap catch-up** or **ad-hoc runs**.

#### Running backfill from your laptop against dev

This runs the Python code locally but connects to dev Cloud SQL. Prerequisites:

1. **Cloud SQL Auth Proxy** running (provides `localhost:5432` → Cloud SQL):
   ```bash
   cloud-sql-proxy i4g-dev:us-central1:i4g-dev-db --port 5432
   ```
2. **gcloud auth** active:
   ```bash
   gcloud auth application-default login
   ```
3. **Env vars** set for dev targeting:
   ```bash
   export I4G_ENV=dev
   export I4G_SSI__SERVICE_URL="https://ssi-<hash>.a.run.app"  # from Terraform output
   export I4G_AUTO_INVESTIGATE__ENABLED=true
   ```

Then run backfill commands normally:

```bash
i4g backfill status                    # check pending work against dev DB
i4g backfill run classify --dry-run    # dry-run first
i4g backfill run classify              # run for real
i4g backfill run all                   # run all tasks
```

Advisory locks prevent concurrent execution, so it is safe to run backfill while Cloud Scheduler jobs are active. The SSI task respects URL deduplication — dozens of cases sharing the same URL trigger only one investigation.

OIDC authentication for SSI is automatic — `google.oauth2.id_token.fetch_id_token()` generates a bearer token using your ADC identity. The SSI service calls back to core at `ssi.core_api_url` (defaults to `https://api.dev.intelligenceforgood.org`).

#### Future: Cloud Run backfill job

A dedicated `backfill-job` Cloud Run job is planned but not yet provisioned. Once available, it will support:

```bash
gcloud run jobs execute backfill-job \
  --region us-central1 \
  --args="backfill,run,all" \
  --project i4g-dev
```

Until then, use the laptop-to-dev pattern above or rely on the existing per-job Cloud Scheduler entries.

### Backfill on Prod

Prod follows the same env-var pattern. All SSI values are injected via Terraform on Cloud Run:

| Setting          | Env Var                         | Value                                 |
| :--------------- | :------------------------------ | :------------------------------------ |
| SSI service URL  | `I4G_SSI__SERVICE_URL`          | Cloud Run URL (Terraform-managed)     |
| Auto-investigate | `I4G_AUTO_INVESTIGATE__ENABLED` | `true`                                |
| Core callback    | `I4G_SSI__CORE_API_URL`         | `https://api.intelligenceforgood.org` |
| OIDC auth        | Automatic                       | Service account identity token        |

For ad-hoc backfill from a laptop against prod (requires prod Cloud SQL Auth Proxy + elevated access):

```bash
export I4G_ENV=prod
i4g backfill run ssi --dry-run    # always dry-run first in prod
i4g backfill run ssi
```

In practice, prod backfill should run via Cloud Run jobs once the `backfill-job` is provisioned — not from developer laptops.

See [Backfill Framework Runbook](backfill_framework.md) for full documentation.

## Data Sources & Design

The bootstrap process uses data bundles from `gs://i4g-dev-data-bundles`. Set `I4G_BOOTSTRAP__USE_GOLDEN_BUNDLE=true` to use the consolidated golden bundle, or leave unset for legacy bundle structure.

For full inventory, licensing, and synthetic scope details, see [Bundle Sources and Synthetic Coverage](../development/bundle_sources_and_coverage.md).

### Maintenance Notes

- **Do not hand-edit `data/`**: Rerun `i4g bootstrap local reset` to restore the baseline.
- **Configuration**: Keep `config/settings.local.toml` aligned when overriding paths.
- **Wipe before re-ingest**: The ingestion pipeline deduplicates by `(dataset, raw_text_sha256)`. If text normalization changes, wipe first to avoid duplicates.
