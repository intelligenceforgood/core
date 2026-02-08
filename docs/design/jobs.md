# Background Jobs & Worker Architecture

> **Status**: Active (v1.1)
> **Last Updated**: February 8, 2026

This document serves as the authoritative inventory of background jobs and worker processes in the I4G Core platform. It maps business logic (Python modules) to deployment artifacts (Docker images) and execution triggers.

## Job Inventory

| Job Name | Purpose | Source Code | Docker Image | Entrypoint / Command |
| :--- | :--- | :--- | :--- | :--- |
| **Ingestion Worker** | Batch processing of data bundles (JSONL). Handles embedding generation and store population. | `src/i4g/worker/jobs/ingest.py` | `ingest-job.Dockerfile` | `i4g jobs ingest` |
| **Intake Worker** | Processes continuous intake streams and new data arrivals. | `src/i4g/worker/jobs/intake.py` | `intake-job.Dockerfile` | `i4g jobs intake` |
| **Report Generator** | Generates PDF/Markdown reports for accepted cases. | `src/i4g/worker/jobs/report.py` | `report-job.Dockerfile` | `i4g jobs report` |
| **Dossier Processor** | Assembles and enriches evidence dossiers from the queue. | `src/i4g/worker/jobs/dossier_queue.py` | `dossier-job.Dockerfile` | `i4g jobs dossier` |
| **Account Manager** | Syncs account watchlists and manages external provider data. | `src/i4g/worker/jobs/account_list.py` | `account-job.Dockerfile` | `/app/scripts/run_account_job.sh` |
| **Ingest Retry** | Retries failed ingestion batches. (Runs within Ingest context or standalone). | `src/i4g/worker/jobs/ingest_retry.py` | *Shared with Ingest* | `i4g jobs ingest-retry` |
| **Classification Sweeper** | Batch fraud classification of pending cases using taxonomy + LLM. | `src/i4g/worker/jobs/classification_sweeper.py` | *Shared with Ingest* | `i4g jobs classify` |
| **PII Backfill** | Tokenizes existing PII in the StructuredStore (backfill utility). | `src/i4g/worker/jobs/pii_backfill.py` | *Shared with Ingest* | `i4g jobs pii-backfill` |

## Detailed Job Descriptions

### 1. Ingestion Worker (`ingest-job`)
*   **Responsibility:** High-throughput processing of static data dumps.
*   **Key Logic:**
    *   Reads JSONL bundles from Cloud Storage.
    *   Performs OCR on attachments (via `tesseract`).
    *   Generates vector embeddings.
    *   Writes to `EntityStore` (SQL) and `VectorStore`.
*   **Infrastructure:** Deployed as a Cloud Run Job. Scaled horizontally based on bundle partitions.

### 2. Intake Worker (`intake-job`)
*   **Responsibility:** Near real-time processing of user submissions.
*   **Key Logic:**
    *   Listens for new case submissions.
    *   Validates and normalizes input data.
    *   Triggers initial risk scoring.
*   **Infrastructure:** Cloud Run Job (Triggered or Polling).

### 3. Report Generator (`report-job`)
*   **Responsibility:** Final artifact generation for law enforcement.
*   **Key Logic:**
    *   Fetches "Accepted" cases from `ReviewStore`.
    *   Renders Jinja2 templates to Markdown.
    *   Converts Markdown to PDF/DOCX.
    *   Uploads artifacts to secure storage.
*   **Infrastructure:** Cloud Run Job (Scheduled).

### 4. Dossier Processor (`dossier-job`)
*   **Responsibility:** Agentic workflow for complex case analysis.
*   **Key Logic:**
    *   Consumes tasks from `DossierQueueStore`.
    *   Executes LangChain agents to gather context.
    *   Synthesizes timeline and relationship graphs.
*   **Infrastructure:** Cloud Run Job (Queue-driven).

### 5. Account Manager (`account-job`)
*   **Responsibility:** Reference data synchronization.
*   **Key Logic:**
    *   Syncs known bad actor lists (crypto addresses, emails).
    *   Updates `EntityStore` reference tables.
*   **Infrastructure:** Cloud Run Job (Scheduled).

## Docker & Deployment
All jobs are containerized using Dockerfiles located in `core/docker/`.
*   **Base Image:** Most jobs share a common Python base with `tesseract-ocr` installed.
*   **Build:** Images are built via `scripts/build_image.sh`.
*   **Registry:** Artifact Registry (`us-central1-docker.pkg.dev/i4g-dev/applications/...`).

For build instructions, see [core/docker/README.md](../../docker/README.md).
