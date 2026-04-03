# Bootstrap Local and Dev Environments

Use these recipes to rebuild or verify the local sandbox and the shared dev environment.

## Prerequisites

Before bootstrapping, you need data bundles in `data/bundles/golden/`. Two ways to get them:

1. **Build locally** (recommended for first-time setup) — see [Prepare Bootstrap Data Bundles](prepare_bootstrap_bundles.md)
2. **Download from GCS** — the bootstrap command auto-downloads if `data/bundles/golden/` is empty:
   ```bash
   # Set RUN_DATE to the bundle date on GCS
   export RUN_DATE=20260330
   ```
   > **Note:** `RUN_DATE` is only consulted when the bundle directory is absent or empty. If
   > `data/bundles/golden/` already exists with files, the download is skipped regardless of
   > `RUN_DATE`. To force a re-download with a different date, delete the directory first:
   > `rm -rf data/bundles/golden/`

The golden bundle contains:

- `cases.jsonl` — consolidated case data (incident responses + synthetic)
- `seed.sql` — campaigns, watchlists, graph edges, timeline data, geography
- `manifest.json` — provenance, counts, SHA-256 hashes

## Bootstrap Design: Fast Ingest → Async Backfill

Bootstrap is designed for **speed**. It loads data quickly and defers expensive processing:

| Step                                    | During Bootstrap      | After Bootstrap (backfill)  |
| :-------------------------------------- | :-------------------- | :-------------------------- |
| Case ingestion                          | ✅ Fast SQLite insert | —                           |
| Seed SQL (campaigns, graph, watchlists) | ✅ Direct SQL         | —                           |
| Analytics aggregation                   | ✅ Auto-runs at end   | —                           |
| LLM classification                      | ❌ Skipped            | `i4g backfill run classify` |
| Risk scoring                            | ❌ Skipped            | Runs with classification    |
| SSI investigation                       | ❌ Skipped            | `i4g backfill run ssi`      |
| Linkage extraction                      | ❌ Skipped            | `i4g backfill run linkage`  |

This means bootstrap completes in minutes. The slow tasks (classification, SSI, linkage) can take hours and are run afterwards via the [Backfill Framework](backfill_framework.md).

## Database Management

### Wipe

```bash
# Local — deletes SQLite, Chroma, reports, manual demo
i4g db wipe local

# Dev — TRUNCATE all data tables in Cloud SQL (preserves schema + accounts)
i4g db wipe dev --confirm "yes-wipe-dev"
```

The wipe command supports `--dry-run` to preview which tables would be affected.

### Backup

```bash
# Local — creates timestamped tar.gz archive
i4g db backup local

# Dev — pg_dump via Cloud SQL Auth Proxy
i4g db backup dev
```

### Restore

```bash
# Local — extract archive to data/
i4g db restore local --from data/backups/backup_local_20250115_120000.tar.gz

# Dev — pg_restore via Cloud SQL Auth Proxy
i4g db restore dev --from gs://i4g-dev-data-bundles/backups/20250115/dump.sql.gz --confirm
```

## Local Sandbox

### Prerequisites

1. **Conda env** `i4g` is active.
2. **Directory**: `core/` root.
3. **Bundles**: Either already in `data/bundles/golden/` or set `RUN_DATE` for GCS download.

### Bootstrap Command

```bash
i4g bootstrap local reset
```

That's it. The command auto-sets `I4G_ENV=local` if not already set. If bundles are present in `data/bundles/golden/`, they are used directly. If not, they are downloaded from GCS using `RUN_DATE` (defaults to `2025-12-17`).

To use a specific bundle date from GCS:

```bash
RUN_DATE=20260330 i4g bootstrap local reset
```

### What the Bootstrap Does

1. Download bundles from GCS (if `data/bundles/golden/` is empty)
2. Reset artifacts (delete SQLite, Chroma, reports)
3. Apply Alembic migrations
4. Seed campaigns
5. Fast-ingest cases into SQLite — cases are stored with pre-classified labels from the bundle;
   no LLM calls are made. `classification_status` is set to `pending` so the backfill sweeper
   can confirm them asynchronously.
6. Apply seed SQL (campaigns, watchlists, graph edges, timeline, geography)
7. OCR processing (if Tesseract available)
8. Rebuild manual demo
9. Seed review cases
10. **Run analytics aggregation** (populates entity_stats, indicator_stats, campaign_stats)
11. Verify sandbox

### Partial Rebuilds

```bash
i4g bootstrap local reset --skip-vector       # skip vector/structured store rebuild
i4g bootstrap local reset --skip-ingest       # skip bundle ingestion (keep existing data)
i4g bootstrap local reset --limit 100         # ingest only 100 records per bundle
```

### Verification

```bash
i4g bootstrap local verify --smoke-search --smoke-dossiers
```

After running, inspect `data/reports/bootstrap_local/` for verification reports.

### Post-Bootstrap: Backfill (Optional but Recommended)

Bootstrap populates the intelligence pages (campaigns, indicators, graph) with seed data. For **full data processing** (LLM classification, risk scoring, linkage extraction), run the backfill framework:

```bash
# Check what needs processing
i4g backfill status

# Run all backfill tasks once (can take hours with LLM classification)
i4g backfill run all

# Or run specific tasks
i4g backfill run classify           # LLM classification + risk scoring
i4g backfill run analytics          # refresh stats tables
i4g backfill run linkage            # extract indicator links via LLM

# Or launch the daemon (continuous loop — fire and forget)
nohup i4g backfill daemon --cycle 60 > data/logs/backfill.log 2>&1 &
```

The daemon is **reentrant** — safe to restart at any time; it picks up where it left off.

#### SSI Backfill (Local)

For SSI auto-investigations of URL indicators, start the SSI dev server in a separate terminal:

```bash
cd ../ssi
conda run -n i4g-ssi uvicorn ssi.api.app:app --reload --port 8100
```

Enable in `config/settings.local.toml`:

```toml
[auto_investigate]
enabled = true
max_concurrent = 3
staleness_days = 30

[ssi]
service_url = "http://localhost:8100"
```

Then run: `i4g backfill run ssi`

See [Backfill Framework Runbook](backfill_framework.md) for full reference.

## Dev Environment (I4G_ENV=dev)

### Prerequisites

1. **GCloud Auth**:
   ```bash
   gcloud auth login
   gcloud auth application-default login
   gcloud config set project i4g-dev
   ```
2. **Impersonation**:
   ```bash
   gcloud config set auth/impersonate_service_account sa-infra@i4g-dev.iam.gserviceaccount.com
   ```

### Bootstrap Command

```bash
i4g bootstrap dev reset \
  --rate-limit-delay 0.5 \
  --timeout 10800 \
  --run-smoke \
  --run-dossier-smoke \
  --run-search-smoke
```

The command auto-sets `I4G_ENV=dev` if not already set — no prefix needed.

Classification is skipped by default (two-phase approach). To enable inline classification (slower):

```bash
i4g bootstrap dev reset --no-skip-classification ...
```

### Verification Only

```bash
i4g bootstrap dev verify \
  --run-smoke \
  --run-dossier-smoke \
  --run-search-smoke
```

### Debugging: Local Execution Against Dev

```bash
RUN_DATE=20260330 i4g bootstrap dev reset \
  --local-execution \
  --rate-limit-delay 0.5
```

### Job Reference

| Job Name           | Docker Image            | Purpose                                           |
| :----------------- | :---------------------- | :------------------------------------------------ |
| `ingest-bootstrap` | `ingest-job.Dockerfile` | Primary ingestion: Cloud SQL, Vertex AI, BigQuery |
| `generate-reports` | `report-job.Dockerfile` | Dossiers, reports, review seeding                 |
| `process-intakes`  | `intake-job.Dockerfile` | Smoke test: processes new intake submissions      |

### Post-Bootstrap: Backfill (Dev)

In dev, Cloud Scheduler already triggers backfill jobs:

| Job                      | Schedule       |
| :----------------------- | :------------- |
| `classification_sweeper` | `*/5 * * * *`  |
| `analytics_aggregation`  | `0 */4 * * *`  |
| `auto_investigate`       | `*/10 * * * *` |

For **post-bootstrap catch-up** or ad-hoc runs from your laptop:

1. Start Cloud SQL Auth Proxy: `cloud-sql-proxy i4g-dev:us-central1:i4g-dev-db --port 5432`
2. Set env: `export I4G_ENV=dev`
3. Run: `i4g backfill status` / `i4g backfill run all`

Advisory locks prevent concurrent execution. Safe to run while Cloud Scheduler is active.

See [Backfill Framework Runbook](backfill_framework.md) for details.

### Backfill on Prod

Same env-var pattern as dev. All SSI values are injected via Terraform on Cloud Run. For ad-hoc runs:

```bash
export I4G_ENV=prod
i4g backfill run ssi --dry-run    # always dry-run first in prod
i4g backfill run ssi
```

In practice, prod backfill should run via Cloud Run jobs — not from developer laptops.

## Environment Selection: I4G_ENV vs CLI Arguments

The CLI uses two distinct patterns to target an environment, depending on the command:

| Command group                                         | Pattern                       | `I4G_ENV` required?                                            |
| :---------------------------------------------------- | :---------------------------- | :------------------------------------------------------------- |
| `db wipe / backup / restore [local\|dev]`             | Explicit positional arg       | No — the arg is the sole authority                             |
| `db migrate / status / grant-permissions [dev\|prod]` | Explicit positional arg       | No — the arg is the sole authority                             |
| `bootstrap local reset`                               | Subcommand encodes the target | Auto-set to `local` if unset; blocks if set to non-`local`     |
| `bootstrap dev reset`                                 | Subcommand encodes the target | Auto-set to `dev` if unset or `local`; blocks if set to `prod` |
| `jobs`, `ingest`, `backfill`, etc.                    | None — reads `I4G_ENV`        | Yes — set explicitly or via container env                      |

**Key rules:**

- `db` commands use the positional argument exclusively. Setting `I4G_ENV` before running them has
  no effect on which database is targeted.
- `bootstrap` commands encode the environment in the subcommand name. Both `bootstrap local` and
  `bootstrap dev` auto-set `I4G_ENV` for you, so no prefix is needed on the command line.
- The `bootstrap local` guard **blocks** if `I4G_ENV` is set to a non-`local` value (protecting
  against running reset while pointed at dev). Use `--force` to override.
- The `bootstrap dev` guard **blocks** only if `I4G_ENV` is explicitly set to `prod`. It allows
  `local` or unset so that developers without a persistent `I4G_ENV` export can still run it.
- `jobs` and similar commands are designed for Cloud Run containers where `I4G_ENV` is injected
  by Terraform. If you run them from your laptop, set `I4G_ENV` explicitly.

## Data Sources & Design

The bootstrap uses data bundles from `gs://i4g-dev-data-bundles/{RUN_DATE}/golden/`. For full inventory, licensing, and synthetic scope details, see [Bundle Sources and Synthetic Coverage](../development/bundle_sources_and_coverage.md).

### Maintenance Notes

- **Do not hand-edit `data/`**: Rerun `i4g bootstrap local reset` to restore the baseline.
- **Configuration**: Keep `config/settings.local.toml` aligned when overriding paths.
- **Wipe before re-ingest**: The ingestion pipeline deduplicates by `(dataset, raw_text_sha256)`. If text normalization changes, wipe first.
