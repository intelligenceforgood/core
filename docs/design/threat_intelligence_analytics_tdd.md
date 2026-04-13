# Threat Intelligence & Fraud Analytics — Technical Design Document

> **Status**: Active (v1.3)
> **Last Updated**: April 2026

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

## 6. Graph Service

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

## 7. Intelligence API

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

---

## 9. Impact Analytics API

The Impact Dashboard provides KPI cards, loss treemap, detection velocity,
pipeline funnel, and cumulative indicator charts. All endpoints live in
`src/i4g/api/impact.py`.

### 9.1 Endpoints

| Method | Path                            | Description                              |
| ------ | ------------------------------- | ---------------------------------------- |
| GET    | `/impact/dashboard`             | KPI cards with vs-prior-period trends    |
| GET    | `/impact/loss-by-taxonomy`      | Loss sums grouped by case classification |
| GET    | `/impact/detection-velocity`    | Proactive vs reactive weekly breakdown   |
| GET    | `/impact/pipeline-funnel`       | Intake→action drop-off stages            |
| GET    | `/impact/cumulative-indicators` | Running totals by indicator category     |

### 9.2 KPI Trend Calculation

Each KPI compares the current period (e.g., last 30 days) against the prior
period of equal length. `_calculate_trend()` returns a direction (`up`, `down`,
`flat`) and a human-readable change string (e.g., `+12 (+8.3%)`).

---

## 10. Campaign Intelligence API

Extends `src/i4g/api/intelligence.py` with campaign browsing, management, and
timeline endpoints.

### 10.1 Endpoints

| Method | Path                                    | Description                               |
| ------ | --------------------------------------- | ----------------------------------------- |
| GET    | `/intelligence/campaigns`               | List campaigns with pagination            |
| GET    | `/intelligence/campaigns/{id}`          | Campaign detail with linked cases         |
| POST   | `/intelligence/campaigns/{id}/manage`   | Rename, merge, split, link/unlink cases   |
| GET    | `/intelligence/campaigns/{id}/timeline` | Daily case counts for a campaign          |
| GET    | `/intelligence/campaigns/{id}/graph`    | Co-occurrence graph for campaign entities |
| GET    | `/intelligence/lea-suggestions`         | LEA referral suggestions scored by risk   |

### 10.2 LEA Referral Engine

`src/i4g/services/lea_referral.py` contains the `LeaReferralEngine` class. It
queries entity-level and campaign-level aggregates, scoring candidates by loss
sum, case count, and risk score. Suggestions exceeding configurable thresholds
(`DEFAULT_LOSS_THRESHOLD = $50k`, `DEFAULT_MIN_CASES = 5`) are surfaced in the
Intelligence Dashboard.

---

## 11. Report Generation & Templates

### 11.1 Report API

Extends `src/i4g/api/reports.py` with generation, library, and download endpoints.

| Method | Path                     | Description                          |
| ------ | ------------------------ | ------------------------------------ |
| POST   | `/reports/generate`      | Queue a report for generation        |
| GET    | `/reports/library`       | List generated reports with metadata |
| GET    | `/reports/{id}/download` | Download a generated report file     |

### 11.2 TLP Labeling

Each template has a default TLP classification per D10:

| Template            | Default TLP |
| ------------------- | ----------- |
| `executive_summary` | TLP:AMBER   |
| `lea_dossier`       | TLP:RED     |
| `campaign_bulletin` | TLP:AMBER   |
| `sar_supplement`    | TLP:AMBER   |

Admin users can override TLP via `options.tlp` in the request body. Invalid
TLP values are rejected with HTTP 400.

### 11.3 Report Templates

- **Executive Summary** (`templates/reports/executive_summary.md.j2`): KPI table,
  loss distribution, detection velocity, pipeline throughput, executive narrative.
- **LEA Dossier** (`templates/reports/lea_dossier.md.j2`): Cover sheet, indicator
  declarations, entity summary, evidence exhibits with SHA-256, integrity manifest.

### 11.4 Chart Rendering

`ReportChartRenderer` in `src/i4g/reports/dossier_visuals.py` generates bar,
line, and funnel charts as PNG images using PIL. Charts are embedded in PDF
reports.

### 11.5 Chain-of-Custody (Two-Tier Hashing)

`src/i4g/reports/dossier_signatures.py` extends the existing signing infrastructure:

- `hash_content()`: SHA-256 hash of a string or bytes content.
- `compute_aggregate_hash()`: Sorts per-record hashes lexicographically and
  computes a single aggregate SHA-256, providing tamper evidence for the full bundle.

---

## 12. Export Adapters

`src/i4g/services/export_adapters.py` implements a protocol-based adapter pattern:

- `ExportAdapter` (Protocol): `serialize(rows, columns) → bytes`, `content_type`,
  `file_extension` properties.
- `CsvAdapter`: Standard CSV with configurable column selection.
- `XlsxAdapter`: Excel workbook via openpyxl (falls back to CSV if unavailable).
- `StixAdapter`: STIX 2.1 JSON bundle with deterministic IDs.
- `get_adapter(format)`: Factory function returning the appropriate adapter.

---

## 13. Key Files

| File                                        | Purpose                              |
| ------------------------------------------- | ------------------------------------ |
| `src/i4g/api/impact.py`                     | Impact Dashboard API router          |
| `src/i4g/services/lea_referral.py`          | LEA referral suggestion engine       |
| `src/i4g/services/export_adapters.py`       | CSV/XLSX/STIX export adapters        |
| `templates/reports/executive_summary.md.j2` | Executive Summary Jinja2 template    |
| `templates/reports/lea_dossier.md.j2`       | LEA Evidence Dossier Jinja2 template |

---

## 14. Network Graph

### 14.1 Graph API

`GET /intelligence/graph` accepts a seed entity, hop count (1-3), optional entity-type
and risk-threshold filters. Returns `GraphPayload` with nodes, edges, and optional
pre-computed layout.

- **GraphService** (`src/i4g/services/graph_service.py`) builds the subgraph from
  `entity_stats` and `entity_links` tables via BFS traversal up to the requested depth.
- **Layout**: For graphs with >500 nodes, `NetworkX.spring_layout` pre-computes
  positions server-side. Layout values are `dict[str, dict[str, float]]` maps
  (`{"x": float, "y": float}` per node).
- **Campaign seeding**: When `campaign_id` is provided, seed entities are drawn
  from the campaign's entity list rather than a single seed.

### 14.2 Graph Export

`GET /intelligence/graph/export` renders the current graph as PNG or SVG.
Accepts `format` (png/svg), `width`, `height`, and `seed`/`hops` parameters.

### 14.3 Frontend Rendering

`network-graph.tsx` renders a canvas-based force-directed graph with color-coded
nodes by entity type and edges by relationship type. Controls include seed input,
hop selector, zoom, and export button.

---

## 15. Taxonomy Explorer

### 15.1 Sankey Endpoint

`GET /impact/taxonomy/sankey` returns `SankeyResponse` with nodes and links
representing the Category → Subcategory flow. Categories are derived by splitting
the `classification` column on `" - "`.

### 15.2 Heatmap Endpoint

`GET /impact/taxonomy/heatmap` returns `HeatmapCell[]` — a two-axis grid of
category × time period with case counts. Supports `granularity` (day/week/month)
and `period` filters.

### 15.3 Trend Endpoint

`GET /impact/taxonomy/trend` returns `TaxonomyTrendPoint[]` — time-series of
case counts per category. Supports `period` and `category` filters.

### 15.4 Data Model

All three endpoints query the `cases` table using the `classification` column.
The `subcategory` is derived at query time by splitting on `" - "` separator.

---

## 16. Geographic Aggregation

### 16.1 Summary Endpoint

`GET /impact/geography` returns `GeographySummary[]` — per-country aggregation
of case count, total loss, and victim count from the `intake_records` table
using the `victim_country` column.

### 16.2 Detail Endpoint

`GET /impact/geography/{country}` returns `CountryDetailResponse` with
individual case records for the specified country, including case ID, category,
and loss amount. Supports `limit` and `period` parameters.

---

## 17. Timeline

### 17.1 Timeline API

`GET /intelligence/timeline` returns `TimelineResponse` with tracks (cases,
indicators, campaigns) over time. Supports `period` (7d/30d/90d/quarter/year)
and `granularity` (day/week/month) parameters.

Weekly KPIs are aggregated from `analytics_kpis` with `date_trunc` by the
requested granularity. Monthly data is retrieved from `analytics_kpis_monthly`.

### 17.2 Frontend Rendering

`timeline-view.tsx` renders horizontal bar charts per track with period/granularity
controls. Tracks are color-coded (blue=cases, green=indicators, amber=campaigns).

---

## 18. Entity Annotations & Status

### 18.1 Annotation Store

`AnnotationStore` (`src/i4g/store/annotation_store.py`) manages CRUD for analyst
notes attached to entities. Annotations have a `target_type` (entity/indicator/
campaign) and `target_id`.

### 18.2 Entity Status Transitions

`PUT /intelligence/entities/{type}/{value}/status` updates entity status
(active/archived/under_review/dismissed). Status is persisted in `entity_stats`.

### 18.3 Bulk Actions

`POST /intelligence/entities/bulk-actions` handles batch operations (export,
tag, status_update) on entity lists. Returns per-entity success/failure results.

---

## 19. Key Files

| File                                                   | Purpose                             |
| ------------------------------------------------------ | ----------------------------------- |
| `src/i4g/services/graph_service.py`                    | Graph traversal and layout engine   |
| `src/i4g/store/annotation_store.py`                    | Entity annotation CRUD store        |
| `src/i4g/api/intelligence.py` (graph section)          | Graph, timeline, annotation, status |
| `src/i4g/api/impact.py` (taxonomy/geo section)         | Sankey, heatmap, trend, geography   |
| `ui/../intelligence/graph/network-graph.tsx`           | Canvas-based graph visualization    |
| `ui/../impact/taxonomy-explorer/taxonomy-explorer.tsx` | Taxonomy explorer component         |
| `ui/../impact/geography/geography-view.tsx`            | Geographic analysis component       |
| `ui/../intelligence/timeline/timeline-view.tsx`        | Timeline visualization component    |

---

## 20. Louvain Community Detection

### 20.1 Algorithm

`GraphService.detect_clusters()` uses `networkx.community.louvain_communities`
with a configurable `resolution` parameter (higher values produce more, smaller
communities). Falls back to `nx.connected_components` when Louvain is unavailable.

### 20.2 Output Schema

Each cluster dict contains:

| Key              | Type            | Description                              |
| ---------------- | --------------- | ---------------------------------------- |
| `id`             | `str`           | Cluster identifier (e.g., `cluster-0`)   |
| `size`           | `int`           | Number of member nodes                   |
| `members`        | `list[str]`     | Sorted node IDs                          |
| `density`        | `float`         | Edge density of the subgraph (0.0–1.0)   |
| `avg_risk_score` | `float`         | Mean risk score across members           |
| `entity_types`   | `dict[str,int]` | Count of each entity type in the cluster |

Clusters smaller than `min_size` (default 3) are excluded.
`enrich_with_clusters()` writes `cluster_id` back to each node for downstream
serialization.

### 20.3 API

`GET /intelligence/graph/clusters?seed={entity}&hops={n}&min_size={m}&resolution={r}`
returns the full graph plus a `clusters` array.

---

## 21. Infrastructure Edge Construction

### 21.1 Clustering Job

`worker/jobs/infrastructure_clustering.py` runs on a configurable interval
(default 6 hours via `I4G_ANALYTICS__INFRASTRUCTURE_CLUSTERING_INTERVAL_HOURS`).

The job:

1. Queries all entities with infrastructure types (ip_address, domain, url,
   hosting_provider, registrar, nameserver, ssl_certificate).
2. Groups entities by case to build co-occurrence pairs.
3. Counts pairwise co-occurrence and classifies edge types using
   `_classify_edge_type()`:
   - `shared_ip` — both entities are IP addresses
   - `shared_registrar` — one entity is a registrar
   - `shared_hosting` — one entity is a hosting provider
   - `shared_case` — fallback for unclassified co-occurrence
4. Upserts edges to the `infrastructure_edges` table with confidence scores.

### 21.2 Table Schema

`infrastructure_edges`: UUID PK, source/target entity type + value,
`edge_type`, `confidence` float, `evidence` JSON, timestamps.

### 21.3 Graph Integration

`GraphService.add_infrastructure_edges()` loads infrastructure edges and adds
them to the NetworkX graph with `relationship="infrastructure"` metadata.

---

## 22. Watchlist & Alert Architecture

### 22.1 WatchlistStore

`store/watchlist_store.py` provides CRUD for watched entities and alerts:

- **Items**: `add_item()`, `remove_item()`, `get_item()`, `list_items()`,
  `update_item()`, `find_by_entity()`, `count_items()`.
- **Alerts**: `create_alert()`, `list_alerts()`, `mark_alert_read()`,
  `mark_all_read()`, `count_unread_alerts()`.

Items have a unique constraint on `(entity_type, canonical_value)`.
`add_item()` returns `None` on duplicate instead of raising.

### 22.2 Watchlist Check Job

`worker/jobs/watchlist_check.py` runs at a configurable interval (default 30
minutes via `I4G_ANALYTICS__WATCHLIST_CHECK_INTERVAL_MINUTES`).

The job iterates watchlist items, queries `entity_stats` for current case
counts, and generates `new_activity` alerts when the count exceeds a stored
baseline. The baseline is tracked via a `[baseline:N]` tag in the item's
`note` field. Loss threshold alerts fire when `total_loss_usd` exceeds
`alert_threshold`.

### 22.3 API Endpoints

Full CRUD on `/intelligence/watchlist/items` and `/intelligence/watchlist/alerts`.
Requires `analyst` role for mutations, `user` role for reads.

---

## 23. Scheduled Report Pipeline

### 23.1 Schedule Model

The `scheduled_reports` table stores recurring report configurations:
`template`, `cadence` (daily/weekly/monthly), `scope` JSON, `options` JSON,
`recipients` JSON, `is_active`, `last_run_at`, `next_run_at`.

### 23.2 Job Logic

`worker/jobs/scheduled_reports.py` checks for due schedules on a configurable
interval (default 15 minutes). For each due schedule it:

1. Calls the existing report generation pipeline with the stored template and scope.
2. Updates `last_run_at` and computes `next_run_at` via `_compute_next_run()`.

CRUD helpers (`create_schedule()`, `list_schedules()`, `deactivate_schedule()`)
are co-located in the job module.

---

## 24. External Enrichment Integration

### 24.1 Passive DNS (SecurityTrails)

`services/enrichment/passive_dns.py` queries the SecurityTrails API for
historical DNS records. `lookup_domain()` returns A, AAAA, MX, NS records.
`lookup_ip()` returns reverse DNS hostnames.

Requires `I4G_ENRICHMENT__SECURITYTRAILS_API_KEY`. Returns a structured
`PassiveDNSResult` dataclass; returns an error result if the key is missing.

### 24.2 ASN Lookup (RDAP)

`services/enrichment/asn_lookup.py` queries the RDAP bootstrap service
(`rdap.org`) for IP-to-ASN information. No API key required. Returns
`ASNInfo` with `network_name`, `cidr`, `asn`, `asn_name`, `country`.

### 24.3 Takedown Verification

`worker/jobs/takedown_check.py` periodically checks URL entities for
reachability. HTTP status codes 404, 410, 451, 502, 503, 521, 523 and
connection errors indicate a takedown. Sets `taken_down_at` on
`entity_stats`. Configured via `I4G_ENRICHMENT__TAKEDOWN_CHECK_INTERVAL_HOURS`
(default 12) and `I4G_ENRICHMENT__TAKEDOWN_MAX_URLS_PER_RUN` (default 200).

---

## 25. Researcher Anonymization Pipeline

### 25.1 Anonymization Layer

`services/anonymizer.py` provides deterministic PII anonymization:

- **PII entity types**: bank_account, phone_number, email, person_name,
  national_id, passport_number, address, credit_card.
- **PII fields**: canonical_value, raw_value, email, phone, name, address,
  account_number, person_name.
- `anonymize_value(value, entity_type)` produces a SHA-256 prefix (16 chars)
  for PII types; non-PII values pass through unchanged.
- `round_loss(amount, precision)` rounds to the nearest $1,000 (default).
- `anonymize_records(records)` batch-processes dicts for export.

### 25.2 Researcher Export

`GET /exports/researcher/entities` returns anonymized entity data as CSV or
JSON. Requires `researcher` role. PII fields are hashed, loss values rounded.

### 25.3 Victim Analytics

`GET /impact/victims` returns aggregate victim demographics: age range
distribution, country breakdown, and contact channel breakdown from
`intake_records`. Requires `analyst` role.

### 25.4 Embeddable Chart Tokens

`POST /intelligence/charts/share` creates a time-limited, read-only share
token for a chart configuration. `GET /intelligence/charts/{token_id}/embed`
retrieves the chart config if the token is valid and not expired.

---

## 26. Key Files

| File                                                    | Purpose                                  |
| ------------------------------------------------------- | ---------------------------------------- |
| `src/i4g/services/graph_service.py`                     | Louvain clustering, temporal snapshots   |
| `src/i4g/store/watchlist_store.py`                      | Watchlist + alert CRUD store             |
| `src/i4g/worker/jobs/watchlist_check.py`                | Watchlist notification job               |
| `src/i4g/worker/jobs/infrastructure_clustering.py`      | Infrastructure edge discovery job        |
| `src/i4g/worker/jobs/takedown_check.py`                 | URL takedown verification job            |
| `src/i4g/worker/jobs/scheduled_reports.py`              | Scheduled report generation job          |
| `src/i4g/services/enrichment/passive_dns.py`            | SecurityTrails passive DNS integration   |
| `src/i4g/services/enrichment/asn_lookup.py`             | RDAP ASN lookup service                  |
| `src/i4g/services/enrichment/blockchain.py`             | Blockchain analytics vendor integration  |
| `src/i4g/api/partner_feed.py`                           | Partner indicator feed API               |
| `src/i4g/services/anonymizer.py`                        | PII anonymization for researcher exports |
| `src/i4g/api/intelligence.py` (watchlist/chart section) | Watchlist CRUD, chart share endpoints    |
| `src/i4g/api/exports.py` (researcher section)           | Anonymized researcher data export        |
| `src/i4g/api/impact.py` (victims section)               | Victim analytics endpoint                |
