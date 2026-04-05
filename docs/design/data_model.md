# Data Model

> **Status**: Active (v2.1)
> **Last Updated**: April 4, 2026

This document describes the relational schema for the i4g platform. All tables are defined
as SQLAlchemy Core `Table` objects in `src/i4g/store/sql.py` and managed via Alembic
migrations.

---

## 1. Database Topology

| Database | MetaData   | Backend (local) | Backend (cloud)        | Purpose                                   |
| -------- | ---------- | --------------- | ---------------------- | ----------------------------------------- |
| Main     | `METADATA` | SQLite          | Cloud SQL (PostgreSQL) | Cases, ingestion, reviews, search, intake |

Engine construction is handled by `build_engine()` in `sql.py`, with caching for the
default-settings path. Cloud SQL connections use `google-cloud-sql-connector` with
`pg8000` and support IAM authentication.

---

## 2. Table Inventory

### 2.1 Ingestion & Campaign Domain

| Table                   | PK                   | Purpose                                                           |
| ----------------------- | -------------------- | ----------------------------------------------------------------- |
| `ingestion_runs`        | `run_id` (UUID)      | Tracks each batch ingestion run (dataset, counts, status, timing) |
| `campaigns`             | `campaign_id` (UUID) | Groups cases by investigation campaign; carries taxonomy rollups  |
| `ingestion_retry_queue` | `retry_id` (UUID)    | Failed writes queued for retry (case_id + backend + payload)      |

### 2.2 Case & Evidence Domain

| Table               | PK                                     | Purpose                                                                                                                                                       |
| ------------------- | -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `cases`             | `case_id` (text)                       | Central entity — one row per reported scam incident. Links to ingestion run and campaign. Carries classification, description (narrative text), status, tags. |
| `source_documents`  | `document_id` (UUID)                   | Evidence documents/chunks tied to a case (text, URL, mime type, score)                                                                                        |
| `entities`          | `entity_id` (UUID)                     | Extracted entities (person, phone, email, etc.) per case, with confidence                                                                                     |
| `entity_mentions`   | `(entity_id, document_id, span_start)` | Join table linking entities to specific text spans in source documents                                                                                        |
| `indicators`        | `indicator_id` (UUID)                  | Fraud indicators (phone numbers, wallet addresses, URLs) linked to cases                                                                                      |
| `indicator_sources` | `(indicator_id, document_id)`          | Join table linking indicators to source documents with evidence scores                                                                                        |

### 2.3 Review & Analyst Workflow

| Table            | PK                 | Purpose                                                                          |
| ---------------- | ------------------ | -------------------------------------------------------------------------------- |
| `review_queue`   | `review_id` (text) | Analyst review work queue — status, priority, assignment, classification results |
| `review_actions` | `action_id` (text) | Audit log of analyst actions on reviews (actor, action, payload, timestamp)      |
| `saved_searches` | `search_id` (text) | Persisted search queries with owner, params, favorites, and tags                 |

### 2.4 Dossier & Report Generation

| Table           | PK               | Purpose                                                                     |
| --------------- | ---------------- | --------------------------------------------------------------------------- |
| `dossier_queue` | `plan_id` (text) | Report generation queue — priority, payload (JSON), status, errors/warnings |

### 2.5 Intake (Victim Submission)

| Table                | PK                     | Purpose                                                                          |
| -------------------- | ---------------------- | -------------------------------------------------------------------------------- |
| `intake_records`     | `intake_id` (text)     | Victim-submitted incident reports (contact info, summary, details, loss amount)  |
| `intake_attachments` | `attachment_id` (text) | Files attached to intake records (filename, content type, storage URI, checksum) |
| `intake_jobs`        | `job_id` (text)        | Async processing jobs for intake records (status, message, metadata)             |

### 2.6 Legacy / Compatibility

| Table          | PK               | Purpose                                                                                                                                                   |
| -------------- | ---------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `scam_records` | `case_id` (text) | Search cache for hybrid retrieval (text, entities, classification, embedding). FK to `cases`. `classification_result` and `tags` columns removed in v2.1. |

### 2.7 Threat Intelligence & Analytics (TIFAP)

| Table                    | PK                               | Purpose                                                                                                   |
| ------------------------ | -------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `threat_campaigns`       | `campaign_id` (text)             | Analyst-managed campaign groupings with lifecycle status, risk score, origin, and taxonomy rollup.        |
| `threat_campaign_cases`  | `(campaign_id, case_id)`         | Junction table linking cases to threat campaigns. Supports many-to-many with link metadata.               |
| `intake_indicator_links` | `(intake_id, indicator_id)`      | Links intake records to financial indicators with confidence scores from LLM extraction or manual review. |
| `entity_stats`           | `(entity_type, canonical_value)` | Pre-computed per-entity aggregate metrics (case count, loss sum, risk scores, campaign IDs).              |
| `indicator_stats`        | `indicator_id`                   | Pre-computed per-indicator aggregate metrics (case count, loss sum, risk score).                          |
| `campaign_stats`         | `campaign_id`                    | Pre-computed per-campaign aggregate metrics (case count, loss, risk score, taxonomy rollup).              |
| `platform_kpis`          | `(period_type, period_start)`    | Daily/weekly operational KPI snapshots (cases, loss, indicators, entities).                               |

**New columns on existing tables** (added by migration `20260312_01`):

- `cases.ingestion_batch_id` — replaces overloaded `campaign_id` for ingestion grouping.
- `intake_records.loss_currency` — ISO 4217 currency code for the reported loss.
- `intake_records.victim_country` — ISO 3166-1 alpha-2 country code.

**Schema normalization** (migration `20260404_01`):

- `cases.description` — narrative text (moved from `scam_records.text`).
- `scam_records.classification_result` — **removed** (authoritative copy in `cases`).
- `scam_records.tags` — **removed** (authoritative copy in `cases`).
- FK constraints added on `review_queue.case_id` and `scam_records.case_id`.
- Entity search (`StructuredStore.search_by_field`) now joins the `entities` table.

See `docs/design/threat_intelligence_analytics_tdd.md` for the full data architecture.

---

## 3. Key Relationships

```
ingestion_runs ──1:N──▶ cases
campaigns ──1:N──▶ cases
cases ──1:N──▶ source_documents
cases ──1:N──▶ entities
cases ──1:N──▶ indicators
entities ──M:N──▶ source_documents (via entity_mentions)
indicators ──M:N──▶ source_documents (via indicator_sources)
indicator_sources ──N:1──▶ entities (optional)
review_queue ──1:N──▶ review_actions
intake_records ──1:N──▶ intake_attachments
intake_records ──1:N──▶ intake_jobs
```

The `cases` table is the central hub. A case belongs to one ingestion run and one campaign.
Each case can have multiple source documents, entities, and indicators.

**FK constraints** (added in migration `20260404_01`):

- `review_queue.case_id` → `cases.case_id` (`ON DELETE CASCADE`)
- `scam_records.case_id` → `cases.case_id` (`ON DELETE CASCADE`)

All display reads (dashboard, case detail, analytics) join `cases` directly.
`scam_records` is retained only as a write-through search cache for `StructuredStore`.

---

## 4. Notable Schema Conventions

- **UUIDs**: Stored as `VARCHAR(64)` to remain backend-agnostic (SQLite + PostgreSQL).
- **JSON columns**: Use `sa.JSON` with a PostgreSQL `JSONB` variant for GIN-indexed queries.
- **Timestamps**: All `DateTime(timezone=True)` with `CURRENT_TIMESTAMP` server defaults.
- **Soft deletes**: `cases` table has `is_deleted` and `deleted_at` columns.
- **Unique constraints**: Prevent duplicate cases (`dataset + raw_text_sha256`), entities, and indicators.
- **Indexes**: Strategy-specific indexes on status, classification, category, and temporal columns.

---

## 5. ER Diagram

The ER diagram is generated with **pgAdmin 4** and stored at:

- **pgAdmin project file**: `docs/assets/design/data_model.pgerd`
- **Exported PNG**: `docs/assets/design/data_model.png`

![ER Diagram](../assets/design/data_model.png)

### Regenerating the diagram

After schema changes in `src/i4g/store/sql.py`:

1. Open **pgAdmin 4** and connect to the dev Cloud SQL database (or a local PostgreSQL instance
   after running `i4g db migrate`).
2. Right-click the database → **ERD For Database**. This auto-discovers all tables and FKs.
3. Arrange the layout as needed (pgAdmin preserves positions in the `.pgerd` file).
4. **File → Save As** → `core/docs/assets/design/data_model.pgerd`
5. **File → Generate/Save as Image** → `core/docs/assets/design/data_model.png`
6. Commit both the `.pgerd` source and the `.png` output.

> **Tip:** "ERD For Database" picks up all tables and foreign keys automatically.
> If new tables don't appear, run the Alembic migration first so the schema is up to date.

---

## 6. Migrations

Schema changes are managed by Alembic.

- `alembic.ini` — main database (`METADATA`)

See `src/i4g/store/sql.py` for the authoritative table definitions.
