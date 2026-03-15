# Docker Images & Jobs

This directory contains Dockerfiles for the various services and background jobs that make up the I4G Core platform.

> **See Also:** For a detailed architectural breakdown of these jobs, their business logic, and execution triggers, please refer to the [Background Jobs & Worker Architecture](../docs/design/jobs.md) guide.

## Service Images

### `core-svc.Dockerfile`

**Service:** Core API
**Entrypoint:** `uvicorn i4g.api.app:app` (implied by base image or deployment config)
**Description:** The main REST API service providing endpoints for reviews, search, and system management.
**Key Dependencies:** `tesseract-ocr` (for on-the-fly extraction), `fastapi`, `uvicorn`.

## Worker Job Images

These images are designed to run as Cloud Run Jobs (batch or triggered tasks).

### `ingest-job.Dockerfile`

**Job:** Ingestion Worker
**Entrypoint:** `i4g jobs ingest`
**Description:** Handles batch ingestion of data bundles (JSONL). It processes records, generates embeddings, and populates the vector and structured stores.
**Key Dependencies:** `tesseract-ocr` (for processing image attachments in bundles).

### `intake-job.Dockerfile`

**Job:** Intake Worker
**Entrypoint:** `i4g jobs intake`
**Description:** Processes continuous or streaming intake sources. It handles new data arriving in the system outside of bulk bundles.
**Key Dependencies:** `tesseract-ocr`.

### `report-job.Dockerfile`

**Job:** Report Generator
**Entrypoint:** `python -m i4g.worker.jobs.report`
**Description:** Generates final PDF/Markdown reports for "accepted" review cases.
**Trigger:** Typically runs on a schedule or is triggered when a review batch is closed.
**Key Dependencies:** `tesseract-ocr` (if reports include OCR'd content verification).

### `dossier-job.Dockerfile`

**Job:** Dossier Queue Processor
**Entrypoint:** `i4g jobs dossier` (or `python -m i4g.worker.jobs.dossier_queue`)
**Description:** Processes the background queue for dossier assembly and enrichment. It handles heavy lifting tasks required to build comprehensive dossiers from raw inputs.
