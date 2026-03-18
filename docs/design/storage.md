# Storage Architecture

> **Status**: Active (v1.1)
> **Last Updated**: February 8, 2026

This document details the storage backends used by the i4g platform across different environments (Local Sandbox vs. Cloud Dev/Prod). The system employs a **polyglot persistence** strategy, using the best tool for each data type (relational, document, vector, blob).

## Storage Matrix

| Data Category   | Component                                                         | Local Sandbox (Laptop)           | Dev / Prod (GCP)         |
| :-------------- | :---------------------------------------------------------------- | :------------------------------- | :----------------------- |
| **Relational**  | `EntityStore` (Ingestion, Entities)                               | **SQLite** (`data/i4g_store.db`) | **Cloud SQL** (Postgres) |
| **Vector**      | `VectorStore` (Embeddings)                                        | **Chroma** (`data/chroma_store`) | **Vertex AI Search**     |
| **Blob/File**   | `EvidenceStorage` (PDFs, Images)                                  | **Local FS** (`data/evidence`)   | **Cloud Storage** (GCS)  |
| **Queue/State** | `ReviewStore` (Analyst Queue)                                     | **SQLite** (`data/i4g_store.db`) | **Cloud SQL** (Postgres) |
| **Agent Queue** | `DossierQueueStore` (Dossier Plans)                               | **SQLite** (`data/i4g_store.db`) | **Cloud SQL** (Postgres) |
| **Analytics**   | `ThreatCampaignStore`, `AnalyticsStore` (Pre-computed aggregates) | **SQLite** (`data/i4g_store.db`) | **Cloud SQL** (Postgres) |

> (\*) **Note on Review Queue**: The `ReviewStore` now uses the shared Cloud SQL instance in cloud environments, ensuring persistent queue state across container restarts.

## Component Details

### 1. Relational Store (SQL)

**Purpose**: The "source of truth" for high-volume structured data generated during ingestion and analyst queue state.

- **Schema**: Defined in `src/i4g/store/sql.py`.
- **Tables** (17 tables in `METADATA`, 1 in `VAULT_METADATA`):
  - `ingestion_runs`: Audit log of batch processing jobs.
  - `campaigns`: Investigation campaign groupings with taxonomy rollups.
  - `cases`: Core case metadata (deduplicated by dataset + hash).
  - `source_documents`: Chunked text from evidence files.
  - `entities`: Extracted entities (person, phone, email, etc.) linked to cases.
  - `entity_mentions`: Join table linking entities to document text spans.
  - `indicators`: Fraud indicators (crypto addresses, emails, phones) with status and confidence.
  - `indicator_sources`: Join table linking indicators to source evidence.
  - `review_queue`: Analyst review work queue (priority, status, assignment).
  - `review_actions`: Audit log of analyst actions on reviews.
  - `saved_searches`: Persisted search queries with owner, params, favorites.
  - `dossier_queue`: Report generation task queue.
  - `intake_records`: Victim-submitted incident reports.
  - `intake_attachments`: Files attached to intake records.
  - `intake_jobs`: Async processing jobs for intake records.
  - `scam_records`: Legacy flat view used by RAG pipeline.
  - `ingestion_retry_queue`: Failed writes queued for retry.
  - `pii_tokens` — **deprecated** (no longer used; see intake encryption in `pii_vault.md`).
- **Access**: Accessed via `EntityStore`, `ReviewStore`, `IntakeStore`, and SQLAlchemy sessions.
- **Full schema reference**: See [data_model.md](data_model.md) for the complete table inventory.
- **Infrastructure**:
  - **Instance**: `i4g-dev-db` (Cloud SQL Postgres 15)
  - **Database**: `i4g_db`
  - **Users**: `ingest_user` (jobs), `app_user` (API)

### 2. Vector Store (Semantic Search)

**Purpose**: Enables natural language search ("find cases about pig butchering") and similarity matching.

- **Content**: Embeddings generated from `source_documents` chunks.
- **Backends**:
  - **Chroma**: Used locally for zero-cost development. Stores artifacts in `data/chroma_store`.
  - **Vertex AI Search**: Managed service used in cloud environments for scalability and managed infrastructure.
- **Access**: Accessed via `VectorStore` and `HybridRetriever`.
- **Infrastructure**:
  - **Data Store ID**: `retrieval-poc`
  - **Location**: `global` (required for Search edition)
  - **Project**: `i4g-dev`

### 3. Blob Storage (Unstructured)

**Purpose**: Storage for raw evidence files (PDFs, screenshots) and generated reports.

- **Buckets**:
  - `evidence`: Raw user uploads and scraped content.
  - `reports`: Generated Markdown/JSON dossiers and investigation reports.
- **Access**: Accessed via `EvidenceStorage` (which abstracts `pathlib` vs `google-cloud-storage`).

### 4. Agent Queue (Dossier)

**Purpose**: Persists "Dossier Plans" for the agentic workflow. This queue decouples the API (which requests a dossier) from the background worker (which executes the LangChain agents).

- **Schema**: Defined in `src/i4g/store/dossier_queue_store.py`.
- **Table**: `dossier_queue`
  - `plan_id`: Unique identifier for the dossier generation task.
  - `status`: `pending`, `leased`, `completed`, `failed`.
  - `payload`: JSON blob containing the initial case context and instructions.
- **Access**: Accessed via `DossierQueueStore`.
- **Infrastructure**: Shares the same SQLite/Cloud SQL instance as the Entity and Review stores.

### 5. Analytics Store (Pre-Computed Aggregates)

**Purpose**: Serves pre-computed statistics for dashboard queries and campaign management.

- **Tables**: `entity_stats`, `indicator_stats`, `campaign_stats`, `platform_kpis`, `threat_campaigns`, `threat_campaign_cases`, `intake_indicator_links`.
- **Refresh Strategy**: The analytics aggregation job (`i4g jobs analytics`) runs every 15 minutes (configurable via `I4G_ANALYTICS__REFRESH_INTERVAL_MINUTES`). Each run upserts aggregate rows idempotently using `dialect_insert()` with `on_conflict_do_update`.
- **Access**: Read queries via `AnalyticsStore`. Campaign CRUD via `ThreatCampaignStore`. Both built through `services/factories.py`.
- **Infrastructure**: Shares the same SQLite/Cloud SQL instance. No separate database needed — aggregate tables are small relative to raw data.

## Data Flow

### Ingestion Pipeline

1.  **Extract**: Bundles (JSONL) are read from source.
2.  **Transform**: Text is chunked, embeddings are generated, and victim contact fields are encrypted.
3.  **Load**:
    - **SQL**: Metadata, entities, and text chunks are written to Cloud SQL/SQLite.
    - **Vector**: Embeddings are upserted to Vertex AI/Chroma.
    - **Blob**: Original files are uploaded to GCS/Local FS.

### Retrieval (Analyst Console)

1.  **Search**: The `HybridRetriever` queries both the **Vector Store** (for semantic matches) and **Entity Store** (for exact indicator matches).
2.  **Merge**: Results are ranked and merged.
3.  **Review**: When an analyst claims a case, the state is tracked in the `ReviewStore` (currently SQLite).
