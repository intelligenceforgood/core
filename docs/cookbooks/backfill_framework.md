# Backfill Framework — Runbook

This runbook describes how to use the **backfill framework** to manage reentrant batch processing tasks across local, dev, and prod environments. The framework unifies all async processing (classification, SSI investigation, analytics, linkage extraction, evidence integrity, and more) under a single CLI with advisory locking, progress reporting, and a launch-and-forget daemon mode.

## Relationship with Bootstrap

Bootstrap intentionally **skips** expensive processing (LLM classification, risk scoring, SSI investigation, linkage extraction) to keep the initial data load fast. After `i4g bootstrap local reset` completes, many cases have `classification_status='pending'` and zero entity/indicator stats. The backfill framework is the standard way to process these asynchronously:

```bash
# After bootstrap — check what's pending, then process
i4g backfill status
i4g backfill run all            # runs all tasks sequentially (can take hours)
# or
i4g backfill daemon --cycle 60  # fire-and-forget continuous processing
```

Bootstrap does automatically run **analytics aggregation** at the end, so intelligence pages (campaigns, graph, watchlist) are populated with seed data immediately. Running the full backfill enriches them with LLM-derived classifications and entity extractions.

### Quick Start: Entity Extraction After Bootstrap

After a local bootstrap, cases may have only rule-based entities from ingestion. Run entity extraction to process them through the full modular extraction pipeline (regex + heuristic + LLM + ML NER, with merge, chunking, and blocklist filtering):

```bash
# Extract entities for cases that have none
i4g backfill run entity-extract

# Re-extract all cases through the full extraction pipeline (replaces ingest-time results)
i4g backfill run entity-extract --backfill

# Or include it in the daemon
i4g backfill daemon --tasks entity-extract --tasks classify --tasks analytics --cycle 60
```

## Concepts

| Term              | Meaning                                                                                                                            |
| :---------------- | :--------------------------------------------------------------------------------------------------------------------------------- |
| **Backfill task** | A named unit of work that discovers unprocessed items and processes them. Each task wraps an existing worker job.                  |
| **Advisory lock** | A database row (`backfill_locks` table) that prevents concurrent execution of the same task. Locks expire automatically after TTL. |
| **Coordinator**   | Runs a single task with locking and structured logging.                                                                            |
| **Daemon**        | Runs all tasks in a continuous loop — the "launch and forget" mode for local development.                                          |

## Registered Tasks

| Name             | Worker Job               | What it Does                                                                                  |
| :--------------- | :----------------------- | :-------------------------------------------------------------------------------------------- |
| `classify`       | `classification_sweeper` | Batch classify cases with `classification_status='pending'` (includes risk score computation) |
| `ssi`            | `auto_investigate`       | Trigger SSI investigations for uninvestigated URL indicators                                  |
| `analytics`      | `analytics_aggregation`  | Refresh pre-computed analytics, campaign risk scores, and KPIs                                |
| `linkage`        | `linkage_extract`        | Extract indicator links from intake narratives via LLM                                        |
| `dossier`        | `dossier_queue`          | Process queued dossier generation jobs                                                        |
| `evidence`       | `evidence_integrity`     | Verify and backfill evidence file SHA-256 checksums                                           |
| `entity-extract` | `entity_extract`         | Extract entities and indicators from cases via LLM + rule-based NER                           |
| `ingest-retry`   | `ingest_retry`           | Retry failed ingestion records                                                                |

## CLI Reference

### Check Pending Work

```bash
i4g backfill status
```

Output shows pending item count, lock status, and description for each task:

```
Task                    Pending          Lock  Description
--------------------------------------------------------------------------------
classify                   7088             -  Batch classify cases with ...
ssi                           0             -  Trigger SSI investigations ...
analytics                     1             -  Refresh pre-computed analytics ...
```

### Run a Single Task

```bash
# Run classification backfill
i4g backfill run classify

# Dry run (no writes)
i4g backfill run ssi --dry-run

# Skip advisory lock (debug only)
i4g backfill run classify --skip-lock

# With custom limit
i4g backfill run ssi --limit 50
```

### Run All Tasks Once

```bash
i4g backfill run all
```

Tasks are executed sequentially. Each acquires its own lock. If a task fails, subsequent tasks still run.

### Launch-and-Forget Daemon (Local Dev)

```bash
# Start the daemon in background — processes all tasks continuously
I4G_ENV=local nohup i4g backfill daemon > data/logs/backfill.log 2>&1 &

# Custom cycle interval (seconds between rounds)
i4g backfill daemon --cycle 120

# Only specific tasks
i4g backfill daemon --tasks classify --tasks ssi --tasks analytics

# Dry run mode
i4g backfill daemon --dry-run
```

The daemon:

1. Queries pending work counts for each task
2. Runs tasks that have items to process
3. Sleeps for `cycle_interval_seconds` (default 300s)
4. Repeats until SIGINT/SIGTERM

Logs are structured and include cycle numbers, task names, pending counts, and execution times. Check progress with:

```bash
tail -f data/logs/backfill.log
```

### Force-Release a Stuck Lock

If a process crashed without releasing its lock:

```bash
i4g backfill unlock classify
```

Locks also expire automatically after their TTL (default 1 hour).

## How Environment Targeting Works

The `i4g backfill` CLI does **not** have an `--env` flag. Like all `i4g` CLI commands, environment targeting is controlled by the `I4G_ENV` environment variable and corresponding `I4G_*` connection settings:

| `I4G_ENV` | Database              | SSI Service       | Auth                         |
| :-------- | :-------------------- | :---------------- | :--------------------------- |
| `local`   | SQLite (in `data/`)   | `localhost:8100`  | None (falls back)            |
| `dev`     | Cloud SQL (via proxy) | Cloud Run service | OIDC (ADC / service account) |
| `prod`    | Cloud SQL (via proxy) | Cloud Run service | OIDC (service account)       |

The CLI runs Python code **on your machine** (or in a Cloud Run container). It is your env vars that determine where the data reads/writes go.

## Environment-Specific Usage

### Local (`I4G_ENV=local`)

After `i4g bootstrap local reset`, cases have `classification_status='pending'`. Start the daemon to process them:

```bash
# Bootstrap already sets I4G_ENV=local, so just run:
i4g bootstrap local reset
nohup i4g backfill daemon --cycle 60 > data/logs/backfill.log 2>&1 &

# Or run specific tasks manually
i4g backfill run classify
i4g backfill run analytics
```

For local SSI: the `ssi` task requires the SSI dev server running. Start it in a separate terminal, then enable auto-investigation in config:

```bash
# Terminal 1 — start SSI service
cd ../ssi
conda run -n i4g-ssi uvicorn ssi.api.app:app --reload --port 8100
```

```toml
# config/settings.local.toml
[auto_investigate]
enabled = true
max_concurrent = 3
staleness_days = 30

[ssi]
service_url = "http://localhost:8100"
```

No OIDC token is needed locally — auth falls back gracefully when the token fetch fails.

### Dev (`I4G_ENV=dev`)

#### Steady-state: Cloud Scheduler handles it

In dev, Cloud Scheduler already triggers the individual Cloud Run jobs that backfill wraps (`classification_sweeper` every 5 min, `analytics_aggregation` every 4 hours, `auto_investigate` every 10 min). You only need the backfill CLI for **post-bootstrap catch-up** or **ad-hoc runs**.

#### Running backfill from your laptop against dev

This runs Python locally but connects to dev Cloud SQL. Prerequisites:

1. **Cloud SQL Auth Proxy** running:
   ```bash
   cloud-sql-proxy i4g-dev:us-central1:i4g-dev-db --port 5432
   ```
2. **gcloud auth** active:
   ```bash
   gcloud auth application-default login
   ```
3. **Env vars** set:
   ```bash
   export I4G_ENV=dev
   export I4G_SSI__SERVICE_URL="https://ssi-<hash>.a.run.app"  # from Terraform output
   export I4G_AUTO_INVESTIGATE__ENABLED=true
   ```

Then use the CLI normally (no `I4G_ENV=dev` prefix needed since it's already exported):

```bash
i4g backfill status                    # check pending work against dev DB
i4g backfill run classify --dry-run    # dry-run first
i4g backfill run classify              # run for real
i4g backfill run all                   # all tasks sequentially
```

Advisory locks prevent concurrent execution, so it is safe to run backfill while Cloud Scheduler jobs are active.

**SSI on dev:** OIDC authentication is automatic — `google.oauth2.id_token.fetch_id_token()` generates a bearer token using your ADC identity. The SSI service calls back to core at `ssi.core_api_url` (defaults to `https://api.dev.intelligenceforgood.org`).

#### Future: Cloud Run backfill job

A dedicated `backfill-job` Cloud Run job is planned but **not yet provisioned**. Once available:

```bash
gcloud run jobs execute backfill-job \
  --region us-central1 \
  --args="backfill,run,all" \
  --project i4g-dev
```

Until then, use the laptop-to-dev pattern above or rely on the existing per-job Cloud Scheduler entries.

### Prod (`I4G_ENV=prod`)

Same env-var pattern as dev. All SSI values are injected via Terraform on Cloud Run:

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

In practice, prod backfill should run via Cloud Run jobs once provisioned — not from developer laptops.

## Concurrency & Race Conditions

### Advisory Locking

Each task acquires a named lock before executing. If another instance is already running the same task, the second instance skips gracefully (exit code -1). This prevents:

- Two sweeper instances classifying the same cases
- Two auto-investigate runs triggering duplicate SSI scans
- Two analytics aggregations running simultaneously

### Lock TTL

Locks expire automatically after their TTL:

| Task             | TTL   | Rationale                                       |
| :--------------- | :---- | :---------------------------------------------- |
| `classify`       | 3600s | Classification can process thousands of cases   |
| `ssi`            | 1800s | SSI triggers are fast; investigations run async |
| `analytics`      | 1800s | Aggregation is bounded by table sizes           |
| `linkage`        | 3600s | LLM extraction is slow                          |
| `dossier`        | 1800s | Bounded by queue size                           |
| `evidence`       | 1800s | I/O bound, predictable time                     |
| `entity-extract` | 3600s | LLM extraction is slow; many cases to process   |
| `ingest-retry`   | 1800s | Small batch sizes                               |

### SSI Deduplication

The SSI task preserves existing deduplication:

1. **URL normalization** — multiple case URLs pointing to the same site are grouped
2. **Scan dedup** — `check_url_duplicate()` checks if a fresh scan exists or is in-progress
3. **Case linking** — if a scan already exists, the case is linked without re-triggering
4. **Domain blocklist** — common benign domains (google.com, etc.) are filtered out

Multiple cases sharing the same URL trigger only one investigation. Stale scans (>30 days) are eligible for re-investigation.

### Multi-User (Tutorial Sessions)

When multiple students submit cases simultaneously:

1. Intake processing runs per-request (no contention)
2. Classification sweeper processes all pending cases (one instance, batch by batch)
3. SSI investigations are rate-limited by `max_concurrent` (default 3 per run)
4. The advisory lock ensures only one sweeper/investigator runs at a time

If throughput is insufficient, increase `sweep.batch_size` or `auto_investigate.max_concurrent`:

```bash
I4G_SWEEP__BATCH_SIZE=50 i4g backfill run classify
```

## Configuration

All settings can be overridden via environment variables:

```bash
# Daemon cycle interval
I4G_BACKFILL__CYCLE_INTERVAL_SECONDS=120

# Lock TTL
I4G_BACKFILL__DEFAULT_LOCK_TTL_SECONDS=7200

# Classification batch size
I4G_SWEEP__BATCH_SIZE=50

# SSI investigation limits
I4G_AUTO_INVESTIGATE__MAX_CONCURRENT=5
I4G_AUTO_INVESTIGATE__ENABLED=true
```

Or in `config/settings.local.toml`:

```toml
[backfill]
cycle_interval_seconds = 120
enabled_tasks = ["classify", "ssi", "analytics"]

[sweep]
batch_size = 50

[auto_investigate]
enabled = true
max_concurrent = 5
```

## Troubleshooting

### "Lock contention — another instance is running"

Another backfill process already holds the lock. Wait for it to complete, or force-release:

```bash
i4g backfill status   # Check which locks are held
i4g backfill unlock classify
```

### Daemon stops processing

Check logs for errors. Common causes:

- Database connection failure
- LLM provider rate limit (classification)
- SSI service unavailable (auto-investigate)

Restart the daemon:

```bash
i4g backfill daemon --cycle 60  # It will pick up where it left off (reentrant)
```

### Large backlog after bootstrap

After a fresh `bootstrap local reset`, expect ~7000+ pending classifications. The daemon will steadily process them. To speed up:

```bash
# Increase batch size
I4G_SWEEP__BATCH_SIZE=50 i4g backfill daemon --tasks classify --cycle 30
```

### SSI not triggering

Verify:

1. `auto_investigate.enabled = true` in settings
2. SSI service is running and reachable (`ssi.service_url`)
3. Cases have URL indicators (`category='url'`, `type='url'`)
4. URLs are not on the domain blocklist
