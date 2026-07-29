# Storage Architecture

> **Status**: Active (v1.2)
> **Last Updated**: April 2026

This document details the storage backends used by the i4g platform across different environments (Local Sandbox vs. Cloud Dev/Prod). The system employs a **polyglot persistence** strategy, using the best tool for each data type (relational, document, vector, blob).

## Storage Matrix

| Data Category   | Component                                                         | Local Sandbox (Laptop)           | Dev / Prod (GCP)         |
| :-------------- | :---------------------------------------------------------------- | :------------------------------- | :----------------------- |
| **Relational**  | `EntityStore` (Ingestion, Entities)                               | **SQLite** (`data/i4g_store.db`) | **Cloud SQL** (Postgres) |
| **Vector**      | `VectorStore` (Embeddings)                                        | **Chroma** (`data/chroma_store`) | **Vertex AI Search**     |
| **Blob/File**   | `EvidenceStorage` (PDFs, Images)                                  | **Local FS** (`data/evidence`)   | **Cloud Storage** (GCS)  |
| **Queue/State** | `ReviewStore` (Analyst Queue)                                     | **SQLite** (`data/i4g_store.db`) | **Cloud SQL** (Postgres) |
| **Engagement**  | `EngagementStore` (Engagements, Analyst Stats)                    | **SQLite** (`data/i4g_store.db`) | **Cloud SQL** (Postgres) |
| **Agent Queue** | `DossierQueueStore` (Dossier Plans)                               | **SQLite** (`data/i4g_store.db`) | **Cloud SQL** (Postgres) |
| **Analytics**   | `ThreatCampaignStore`, `AnalyticsStore` (Pre-computed aggregates) | **SQLite** (`data/i4g_store.db`) | **Cloud SQL** (Postgres) |
| **Annotation**  | `AnnotationStore`, `WatchlistStore` (User annotations, alerts)    | **SQLite** (`data/i4g_store.db`) | **Cloud SQL** (Postgres) |
| **SSI**         | `SsiStore`, `SsiEventsStore` (Site investigations)                | **SQLite** (`data/i4g_store.db`) | **Cloud SQL** (Postgres) |

> (\*) **Note on Review Queue**: The `ReviewStore` now uses the shared Cloud SQL instance in cloud environments, ensuring persistent queue state across container restarts.

## Component Details

### 1. Relational Store (SQL)

**Purpose**: The "source of truth" for high-volume structured data generated during ingestion and analyst queue state.

- **Schema**: Defined in `src/i4g/store/sql.py`.
- **Tables** (~45 tables in `METADATA`):
  - **Ingestion & Cases**: `ingestion_runs`, `campaigns`, `cases`, `source_documents`, `scam_records`, `ingestion_retry_queue`.
  - **Entities & Indicators**: `entities`, `entity_mentions`, `indicators`, `indicator_sources`.
  - **Review & Queue**: `review_queue`, `review_actions`, `saved_searches`, `dossier_queue`.
  - **Intake**: `intake_records`, `intake_attachments`, `intake_jobs`.
  - **Engagements**: `engagements`, `engagement_analyst_stats`.
  - **Accounts**: `accounts`, `account_actions`.
  - **Annotations & Watchlists**: `annotations`, `watchlist_items`, `watchlist_alerts`.
  - **SSI (Site Investigation)**: `site_scans`, `case_investigations`, `harvested_wallets`, `agent_sessions`, `pii_exposures`, `ssi_events`, `ssi_guidance_commands`.
  - **Analytics (pre-computed)**: `entity_stats`, `indicator_stats`, `campaign_stats`, `platform_kpis`, `threat_campaigns`, `threat_campaign_cases`, `intake_indicator_links`.
  - **Infrastructure**: `infrastructure_edges`, `scheduled_reports`, `chart_share_tokens`, `api_keys`, `partner_feed_audit`, `audit_log`, `backfill_locks`.
  - `pii_tokens` — **removed** (superseded by intake Fernet encryption; see [pii_protection.md](pii_protection.md)).
- **Access**: Accessed via `EntityStore`, `ReviewStore`, `IntakeStore`, `EngagementStore`, `AnnotationStore`, `WatchlistStore`, and SQLAlchemy sessions.
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

### 4. Engagement Store

**Purpose**: Manages engagement lifecycle — grouping cases into analyst-led investigations with tracked progress and analyst statistics.

- **Tables**: `engagements`, `engagement_analyst_stats`.
- **Access**: Accessed via `EngagementStore`, built through `services/factories.py`.
- **Infrastructure**: Shares the same SQLite/Cloud SQL instance.

### 5. Agent Queue (Dossier)

**Purpose**: Persists "Dossier Plans" for the agentic workflow. This queue decouples the API (which requests a dossier) from the background worker (which executes the LangChain agents).

- **Schema**: Defined in `src/i4g/store/dossier_queue_store.py`.
- **Table**: `dossier_queue`
  - `plan_id`: Unique identifier for the dossier generation task.
  - `status`: `pending`, `leased`, `completed`, `failed`.
  - `payload`: JSON blob containing the initial case context and instructions.
  - `priority`, `queued_at`, `updated_at`, `error`, `warnings`: Scheduling and diagnostics.
- **Access**: Accessed via `DossierQueueStore`.
- **Infrastructure**: Shares the same SQLite/Cloud SQL instance as the Entity and Review stores.

### 6. Annotation & Watchlist Stores

**Purpose**: User-created annotations on entities/cases and watchlist alerts for monitored indicators.

- **Tables**: `annotations`, `watchlist_items`, `watchlist_alerts`.
- **Access**: Accessed via `AnnotationStore` and `WatchlistStore`, built through `services/factories.py`.
- **Infrastructure**: Shares the same SQLite/Cloud SQL instance.

### 7. SSI Stores (Site Investigation)

**Purpose**: Persists Scam Site Investigator results — site scans, harvested wallets, PII exposures, and agent session state. Managed by the `ssi` repo but stored in the shared database.

- **Tables**: `site_scans`, `case_investigations`, `harvested_wallets`, `agent_sessions`, `pii_exposures`, `ssi_events`, `ssi_guidance_commands`.
- **Access**: Accessed via `SsiStore` and `SsiEventsStore`, built through `services/factories.py`.
- **Infrastructure**: Shares the same SQLite/Cloud SQL instance.

### 8. Analytics Store (Pre-Computed Aggregates)

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
3.  **Review**: When an analyst claims a case, the state is tracked in the `ReviewStore` (SQLite locally, Cloud SQL in cloud environments).
