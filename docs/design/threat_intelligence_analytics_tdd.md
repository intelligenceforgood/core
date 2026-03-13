# Threat Intelligence & Fraud Analytics — Technical Design Document

> **Status**: Active (v1.0)
> **Sprint**: S1 — Data Foundation
> **Last Updated**: March 2026

---

## 1. Overview

This TDD describes the data architecture for the Threat Intelligence & Fraud Analytics
Platform (TIFAP). It covers the aggregation pipeline, pre-computed analytics tables,
campaign model, loss-indicator linkage, and PII anonymization model.

For the product specification, see `planning/prd_threat_intelligence_analytics.md`.

---

## 2. Data Architecture

### 2.1 Aggregation Pipeline

The analytics aggregation job (`src/i4g/worker/jobs/analytics_aggregation.py`) pre-computes
statistics from raw tables into four aggregate tables:

```
cases + entities → entity_stats
indicators + intake_records → indicator_stats
threat_campaigns + cases → campaign_stats
cases + intake_records → platform_kpis
```

The job runs on a configurable interval (default: 15 minutes) set via
`I4G_ANALYTICS__REFRESH_INTERVAL_MINUTES`. Each run is idempotent — aggregate rows are
upserted via `dialect_insert()` with `on_conflict_do_update`.

### 2.2 Pre-Computed Tables

| Table             | Primary Key                      | Aggregates From                                       | Purpose                                  |
| ----------------- | -------------------------------- | ----------------------------------------------------- | ---------------------------------------- |
| `entity_stats`    | `(entity_type, canonical_value)` | `entities`, `cases`, `intake_records`                 | Per-entity risk, loss, and victim counts |
| `indicator_stats` | `indicator_id`                   | `indicators`, `cases`, `intake_indicator_links`       | Per-indicator case frequency and loss    |
| `campaign_stats`  | `campaign_id`                    | `threat_campaigns`, `cases`, `entities`, `indicators` | Campaign-level metrics and risk scores   |
| `platform_kpis`   | `(period_type, period_start)`    | `cases`, `intake_records`, `indicators`, `entities`   | Daily/weekly operational metrics         |

### 2.3 BigQuery Migration Path

The current implementation targets Cloud SQL (PostgreSQL) for both raw and aggregate
storage. A future sprint will add a BigQuery export step for historical analytics and
dashboard queries that exceed Cloud SQL capabilities. The aggregate table schema is
designed to be BigQuery-compatible (no PostgreSQL-specific types).

---

## 3. Campaign Model

### 3.1 Threat Campaigns vs. Ingestion Batches

The platform separates two concepts that were previously conflated:

- **Ingestion Batch** (`cases.ingestion_batch_id`): A group of cases ingested together
  from a single data source. Purely operational — no analytical meaning.
- **Threat Campaign** (`threat_campaigns` + `threat_campaign_cases`): An analyst-managed
  grouping of cases that represent a coordinated fraud operation. Supports lifecycle
  management, risk scoring, and taxonomy rollup.

Cases link to campaigns via the `threat_campaign_cases` junction table. A case can belong
to multiple campaigns. Campaigns can be merged or split by analysts.

### 3.2 Campaign Lifecycle

Campaigns follow a lifecycle defined in PRD Section 7.3:

```
emerging → active → declining → dormant → closed
```

Transitions are automatic (based on inactivity) except for `closed`, which requires
explicit analyst action. The aggregation job evaluates transitions on each run:

- **active**: Any linked case created/updated in the last 14 days.
- **declining**: No new case activity for 14–30 days.
- **dormant**: No new case activity for 30+ days.
- **closed**: Terminal state — analyst-initiated only.

### 3.3 Campaign Risk Score

Campaign risk score is computed with a weighted formula (PRD Section 7.5):

```
score = (case_norm × w_case + loss_norm × w_loss + avg_risk_norm × w_risk
         + recency × w_recency + diversity × w_diversity) × 100
```

Default weights are configurable via `I4G_ANALYTICS__CAMPAIGN_RISK_WEIGHTS`:

| Factor                | Weight | Normalization                                   |
| --------------------- | ------ | ----------------------------------------------- |
| `case_count`          | 0.15   | `min(count / 50, 1.0)`                          |
| `loss_sum`            | 0.30   | `min(sum / 1,000,000, 1.0)`                     |
| `avg_risk`            | 0.25   | `avg / 100`                                     |
| `recency`             | 0.15   | 1.0 (<7d), 0.75 (<30d), 0.5 (<90d), 0.25 (else) |
| `indicator_diversity` | 0.15   | `min(types / 8, 1.0)`                           |

---

## 4. Loss-Indicator Linkage

### 4.1 Intake-Indicator Links

The `intake_indicator_links` table connects intake records (victim reports) to financial
indicators. Links are created by:

1. **LLM Extraction Job** (`src/i4g/worker/jobs/linkage_extract.py`): Parses intake
   narrative text to identify mentioned financial indicators and matches them against the
   `indicators` table.
2. **Manual linking**: Analysts can link intake records to indicators via the API.

Each link includes a confidence score. The `I4G_ANALYTICS__LOSS_LINKAGE_CONFIDENCE_THRESHOLD`
setting (default: 0.6) filters low-confidence links during aggregation.

### 4.2 Loss Attribution

Entity and campaign loss sums are derived from intake records linked to cases associated
with the entity or campaign. The aggregation path:

```
entity → cases (via entities.case_id) → intake_records (via case_id) → loss_amount
campaign → cases (via threat_campaign_cases) → intake_records → loss_amount
```

---

## 5. PII Anonymization Model

### 5.1 Soft Anonymization

When all cases referencing a specific entity (by `entity_type` + `canonical_value`) have
been purged (`cases.purged_at IS NOT NULL`), the entity's `canonical_value` in
`entity_stats` is replaced with its SHA-256 hash and `purge_status` is set to
`"anonymized"`.

This preserves aggregate statistics (counts, scores) while removing PII. The
anonymization check runs as the final step of each aggregation cycle.

### 5.2 Design Constraints

- Anonymization is one-way — the original value cannot be recovered from the hash.
- Only `entity_stats` is anonymized; raw `entities` rows are handled by the retention
  purge job.
- The check examines all entity_stats rows where `purge_status IS NULL` on each run.

---

## 6. Graph Service (Sprint 2)

The `GraphService` (`src/i4g/services/graph_service.py`) implements in-memory
co-occurrence analysis using NetworkX. It accepts entity → case adjacency data
and builds an undirected weighted graph where edges represent shared cases.

### 6.1 Operations

| Method              | Description                                                  |
| ------------------- | ------------------------------------------------------------ |
| `get_neighbors()`   | 1- or 2-hop BFS with optional entity-type filter             |
| `get_subgraph()`    | Extract a subgraph for a list of node IDs                    |
| `detect_clusters()` | Louvain community detection (fallback: connected components) |
| `compute_layout()`  | Server-side spring layout for graphs ≥ 500 nodes             |
| `serialize()`       | Full graph payload (nodes, edges, counts, optional layout)   |

### 6.2 Protocol

`GraphServiceProtocol` allows future swaps (e.g., Neo4j) without changing
callers. The existing `EntityGraphTool` in `dossier_tools.py` delegates to
`GraphService` with a `try/except` fallback to the legacy path.

---

## 7. Intelligence API (Sprint 2)

### 7.1 Endpoints

| Route                                                              | Method | Description                             |
| ------------------------------------------------------------------ | ------ | --------------------------------------- |
| `/intelligence/entities`                                           | GET    | Paginated entity stats list             |
| `/intelligence/entities/{entity_type}/{canonical_value}`           | GET    | Entity detail with campaign links       |
| `/intelligence/entities/{entity_type}/{canonical_value}/activity`  | GET    | Weekly sparkline data                   |
| `/intelligence/entities/{entity_type}/{canonical_value}/neighbors` | GET    | 1-hop co-occurrence graph               |
| `/intelligence/indicators`                                         | GET    | Paginated indicator stats list          |
| `/intelligence/indicators/{indicator_id}`                          | GET    | Indicator detail                        |
| `/intelligence/dashboard`                                          | GET    | Widget aggregates                       |
| `/intelligence/search/facets`                                      | GET    | Entity type / indicator category facets |
| `/exports/entities`                                                | GET    | Entity CSV/XLSX export                  |
| `/exports/indicators`                                              | GET    | Indicator CSV/XLSX/STIX export          |

### 7.2 Role-based Access (D16)

The `researcher` role (below `user` in the hierarchy) receives anonymized data:

- **Entity list**: `canonical_value` masked to `***` + last 4 chars.
- **Entity/Indicator detail**: returns HTTP 403.
- **Indicator list**: `indicator_value` masked similarly.
- **Exports**: bank indicator values masked to `****` + last 4 digits by default.
  `?unmask=true` requires `analyst` or higher role.

### 7.3 Response Models

All response models inherit `CamelModel` (JSON output is camelCase).
Key models: `EntityListResponse`, `IndicatorListResponse`,
`DashboardWidgetsResponse`, `NeighborGraphResponse`.

---

## 8. Key Files

| File                                                          | Purpose                                         |
| ------------------------------------------------------------- | ----------------------------------------------- |
| `src/i4g/store/sql.py`                                        | Table definitions (7 new tables, 3 new columns) |
| `src/i4g/store/threat_campaign_store.py`                      | Campaign CRUD, merge, split                     |
| `src/i4g/store/analytics_store.py`                            | Read-only queries for aggregate tables          |
| `src/i4g/worker/jobs/analytics_aggregation.py`                | Aggregation job entry point                     |
| `src/i4g/worker/jobs/linkage_extract.py`                      | LLM indicator extraction job                    |
| `src/i4g/settings/sections/jobs.py`                           | `AnalyticsSettings` configuration               |
| `src/i4g/services/factories.py`                               | Store factory functions                         |
| `src/i4g/services/graph_service.py`                           | GraphService — NetworkX co-occurrence analysis  |
| `src/i4g/api/intelligence.py`                                 | Intelligence API router (entities, indicators)  |
| `src/i4g/api/exports.py`                                      | Export router (CSV, XLSX, STIX 2.1)             |
| `src/i4g/api/roles.py`                                        | Role enum, hierarchy, `has_role()`              |
| `src/i4g/migrations/versions/20260312_01_add_tifap_tables.py` | Alembic migration                               |
