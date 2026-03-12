# Background Jobs & Worker Architecture

> **Status**: Active (v1.1)
> **Last Updated**: February 8, 2026

This document serves as the authoritative inventory of background jobs and worker processes in the I4G Core platform. It maps business logic (Python modules) to deployment artifacts (Docker images) and execution triggers.

## Job Inventory

| Job Name                   | Purpose                                                                                                                                                                    | Source Code                                     | Docker Image             | Entrypoint / Command              |
| :------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :---------------------------------------------- | :----------------------- | :-------------------------------- |
| **Ingestion Worker**       | Batch processing of data bundles (JSONL). Handles embedding generation and store population.                                                                               | `src/i4g/worker/jobs/ingest.py`                 | `ingest-job.Dockerfile`  | `i4g jobs ingest`                 |
| **Intake Worker**          | Processes continuous intake streams and new data arrivals.                                                                                                                 | `src/i4g/worker/jobs/intake.py`                 | `intake-job.Dockerfile`  | `i4g jobs intake`                 |
| **Report Generator**       | Generates PDF/Markdown reports for accepted cases.                                                                                                                         | `src/i4g/worker/jobs/report.py`                 | `report-job.Dockerfile`  | `i4g jobs report`                 |
| **Dossier Processor**      | Assembles and enriches evidence dossiers from the queue.                                                                                                                   | `src/i4g/worker/jobs/dossier_queue.py`          | `dossier-job.Dockerfile` | `i4g jobs dossier`                |
| **Account Manager**        | Syncs account watchlists and manages external provider data.                                                                                                               | `src/i4g/worker/jobs/account_list.py`           | `account-job.Dockerfile` | `/app/scripts/run_account_job.sh` |
| **Ingest Retry**           | Retries failed ingestion batches. (Runs within Ingest context or standalone).                                                                                              | `src/i4g/worker/jobs/ingest_retry.py`           | _Shared with Ingest_     | `i4g jobs ingest-retry`           |
| **Classification Sweeper** | Batch fraud classification of pending cases using taxonomy + LLM.                                                                                                          | `src/i4g/worker/jobs/classification_sweeper.py` | _Shared with Ingest_     | `i4g jobs classify`               |
| **PII Backfill**           | Tokenizes existing PII in the StructuredStore (backfill utility).                                                                                                          | `src/i4g/worker/jobs/pii_backfill.py`           | _Shared with Ingest_     | `i4g jobs pii-backfill`           |
| **Retention Purge**        | Two-phase data retention: soft-deletes resolved cases past their retention window, then hard-purges after a grace period (including PII vault, evidence, and vector data). | `src/i4g/worker/jobs/retention_purge.py`        | _Shared with Ingest_     | `i4g jobs retention-purge`        |
| **Analytics Aggregation**  | Pre-computes entity, indicator, campaign stats and platform KPIs. Includes campaign risk scoring, lifecycle transitions, and PII anonymization.                            | `src/i4g/worker/jobs/analytics_aggregation.py`  | _Shared with Ingest_     | `i4g jobs analytics`              |
| **Linkage Extraction**     | LLM-driven extraction of financial indicators from intake narratives, writing `intake_indicator_links` with confidence scores.                                             | `src/i4g/worker/jobs/linkage_extract.py`        | _Shared with Ingest_     | `i4g jobs linkage-extract`        |

## Detailed Job Descriptions

### 1. Ingestion Worker (`ingest-job`)

- **Responsibility:** High-throughput processing of static data dumps.
- **Key Logic:**
  - Reads JSONL bundles from Cloud Storage.
  - Performs OCR on attachments (via `tesseract`).
  - Generates vector embeddings.
  - Writes to `EntityStore` (SQL) and `VectorStore`.
- **Infrastructure:** Deployed as a Cloud Run Job. Scaled horizontally based on bundle partitions.

### 2. Intake Worker (`intake-job`)

- **Responsibility:** Near real-time processing of user submissions.
- **Key Logic:**
  - Listens for new case submissions.
  - Validates and normalizes input data.
  - Triggers initial risk scoring.
- **Infrastructure:** Cloud Run Job (Triggered or Polling).

### 3. Report Generator (`report-job`)

- **Responsibility:** Final artifact generation for law enforcement.
- **Key Logic:**
  - Fetches "Accepted" cases from `ReviewStore`.
  - Renders Jinja2 templates to Markdown.
  - Converts Markdown to PDF/DOCX.
  - Uploads artifacts to secure storage.
- **Infrastructure:** Cloud Run Job (Scheduled).

### 4. Dossier Processor (`dossier-job`)

- **Responsibility:** Agentic workflow for complex case analysis.
- **Key Logic:**
  - Consumes tasks from `DossierQueueStore`.
  - Executes LangChain agents to gather context.
  - Synthesizes timeline and relationship graphs.
- **Infrastructure:** Cloud Run Job (Queue-driven).

### 5. Account Manager (`account-job`)

- **Responsibility:** Reference data synchronization.
- **Key Logic:**
  - Syncs known bad actor lists (crypto addresses, emails).
  - Updates `EntityStore` reference tables.
- **Infrastructure:** Cloud Run Job (Scheduled).

### 6. Retention Purge (`retention-purge`)

- **Responsibility:** Automated data lifecycle management and GDPR compliance.
- **Key Logic:**
  - **Phase 1** — Soft-deletes resolved cases older than `retention_days` (default 90).
  - **Phase 2** — Hard-purges soft-deleted cases older than `retention_grace_days` (default 30), removing all related data: source documents, entities, indicators, review-queue entries, PII vault tokens, evidence files, and vector embeddings.
  - Gated by `retention_enabled` setting (master kill-switch).
  - Supports `--dry-run` for safe pre-production validation.
- **Infrastructure:** Cloud Run Job (Scheduled via Cloud Scheduler, daily at 03:00 UTC).
- **Runbook:** [docs/runbooks/retention_purge.md](../runbooks/retention_purge.md)

### 7. Analytics Aggregation (`analytics`)

- **Responsibility:** Pre-compute aggregate tables from raw data for dashboard queries.
- **Key Logic:**
  - Refreshes `entity_stats`, `indicator_stats`, `campaign_stats`, and `platform_kpis`.
  - Computes campaign risk scores (PRD Section 7.5 weighted formula).
  - Performs automatic lifecycle transitions (emerging → active → declining → dormant).
  - Computes taxonomy rollup from member case classifications.
  - Anonymizes entity_stats for fully purged cases (PII soft-anonymization).
- **Env Vars:** `I4G_ANALYTICS__REFRESH_INTERVAL_MINUTES` (default 15), `I4G_ANALYTICS__CAMPAIGN_RISK_WEIGHTS`.
- **Infrastructure:** Cloud Run Job (Scheduled via Cloud Scheduler, every 15 minutes).

### 8. Linkage Extraction (`linkage-extract`)

- **Responsibility:** Identify financial indicators in intake narratives using LLM.
- **Key Logic:**
  - Selects intake records without existing `intake_indicator_links`.
  - Sends narrative text to the configured LLM provider.
  - Parses structured JSON response and matches against the `indicators` table.
  - Writes `intake_indicator_links` with confidence scores.
  - Supports `--backfill` flag to reprocess all intakes.
- **Env Vars:** `I4G_ANALYTICS__LOSS_LINKAGE_CONFIDENCE_THRESHOLD` (default 0.6), `I4G_LLM__PROVIDER`.
- **Infrastructure:** Cloud Run Job (Triggered after intake processing or scheduled).

## Docker & Deployment

All jobs are containerized using Dockerfiles located in `core/docker/`.

- **Base Image:** Most jobs share a common Python base with `tesseract-ocr` installed.
- **Build:** Images are built via `scripts/build_image.sh`.
- **Registry:** Artifact Registry (`us-central1-docker.pkg.dev/i4g-dev/applications/...`).

For build instructions, see [core/docker/README.md](../../docker/README.md).
