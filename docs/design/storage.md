# Storage Architecture

> **Status**: Active
> **Last Updated**: December 20, 2025

This document details the storage backends used by the i4g platform across different environments (Local Sandbox vs. Cloud Dev/Prod). The system employs a **polyglot persistence** strategy, using the best tool for each data type (relational, document, vector, blob).

## Storage Matrix

| Data Category | Component | Local Sandbox (Laptop) | Dev / Prod (GCP) |
| :--- | :--- | :--- | :--- |
| **Relational** | `EntityStore` (Ingestion, Entities) | **SQLite** (`data/i4g_store.db`) | **Cloud SQL** (Postgres) |
| **Document** | `FirestoreWriter` (Case Metadata) | **Mock/No-op** (or SQLite) | **Firestore** (Native Mode) |
| **Vector** | `VectorStore` (Embeddings) | **Chroma** (`data/chroma_store`) | **Vertex AI Search** |
| **Blob/File** | `EvidenceStorage` (PDFs, Images) | **Local FS** (`data/evidence`) | **Cloud Storage** (GCS) |
| **Queue/State** | `ReviewStore` (Analyst Queue) | **SQLite** (`data/i4g_store.db`) | **Cloud SQL** (Postgres) |

> (*) **Note on Review Queue**: The `ReviewStore` now uses the shared Cloud SQL instance in cloud environments, ensuring persistent queue state across container restarts.

## Component Details

### 1. Relational Store (SQL)
**Purpose**: The "source of truth" for high-volume structured data generated during ingestion and analyst queue state.
- **Schema**: Defined in `src/i4g/store/sql.py`.
- **Tables**:
    - `ingestion_runs`: Audit log of batch processing jobs.
    - `cases`: Core case metadata (deduplicated by dataset + hash).
    - `entities`: Extracted indicators (crypto addresses, emails, phones) linked to cases.
    - `source_documents`: Chunked text from evidence files.
    - `reviews`: Analyst review queue items and status.
- **Access**: Accessed via `EntityStore`, `ReviewStore`, and SQLAlchemy sessions.
- **Infrastructure**:
    - **Instance**: `i4g-dev-db` (Cloud SQL Postgres 15)
    - **Database**: `i4g_db`
    - **Users**: `ingest_user` (jobs), `app_user` (API)

### 2. Document Store (NoSQL)
**Purpose**: Flexible storage for case documents that need real-time updates or schema evolution.
- **Usage**: The ingestion pipeline performs a "dual-write" to both SQL and Firestore to ensure data availability for different access patterns.
- **Collections**:
    - `cases`: Stores the full JSON representation of a case.
- **Access**: Accessed via `FirestoreWriter`.

### 3. Vector Store (Semantic Search)
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

### 4. Blob Storage (Unstructured)
**Purpose**: Storage for raw evidence files (PDFs, screenshots) and generated reports.
- **Buckets**:
    - `evidence`: Raw user uploads and scraped content.
    - `reports`: Generated Markdown/JSON dossiers and investigation reports.
- **Access**: Accessed via `EvidenceStorage` (which abstracts `pathlib` vs `google-cloud-storage`).

## Data Flow

### Ingestion Pipeline
1.  **Extract**: Bundles (JSONL) are read from source.
2.  **Transform**: Text is chunked, PII is tokenized (if enabled), and embeddings are generated.
3.  **Load**:
    - **SQL**: Metadata, entities, and text chunks are written to Cloud SQL/SQLite.
    - **Vector**: Embeddings are upserted to Vertex AI/Chroma.
    - **Firestore**: Case documents are upserted to Firestore (Cloud only).
    - **Blob**: Original files are uploaded to GCS/Local FS.

### Retrieval (Analyst Console)
1.  **Search**: The `HybridRetriever` queries both the **Vector Store** (for semantic matches) and **Entity Store** (for exact indicator matches).
2.  **Merge**: Results are ranked and merged.
3.  **Review**: When an analyst claims a case, the state is tracked in the `ReviewStore` (currently SQLite).
