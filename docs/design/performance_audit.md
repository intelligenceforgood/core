# Performance Audit — TIFAP Sprint 6

**Date:** Sprint 6 Final
**Scope:** Dashboard load times, graph rendering, aggregation job throughput

## Dashboard Load Time Targets

| Endpoint                       | Target | Notes                                        |
| ------------------------------ | ------ | -------------------------------------------- |
| `GET /impact/dashboard`        | < 2 s  | 5 parallel API calls, KPI aggregations       |
| `GET /impact/loss`             | < 1 s  | Single GROUP BY on classification            |
| `GET /impact/velocity`         | < 1 s  | Time-bucket aggregation on review_actions    |
| `GET /impact/funnel`           | < 1 s  | Pipeline stage counts                        |
| `GET /impact/cumulative`       | < 1 s  | Cumulative indicator growth by category      |
| `GET /intelligence/entities`   | < 2 s  | Paginated entity_stats with optional filters |
| `GET /intelligence/indicators` | < 2 s  | Paginated indicator_stats                    |
| `GET /intelligence/campaigns`  | < 2 s  | Campaign listing with stats join             |
| `GET /intelligence/graph/{id}` | < 3 s  | NetworkX subgraph for < 500 nodes            |

## Graph Rendering

- **Target:** < 3 s for 500-node force-directed graph in the browser
- **Strategy:** Server-side NetworkX computes layout coordinates; client renders with D3/Recharts
- **Mitigations:** Pagination of large graphs, cluster-level summary nodes for > 500 nodes

## Database Index Additions (S6-15)

Added the following indexes to cover analytics query hot paths:

| Table             | Index                                 | Columns                      |
| ----------------- | ------------------------------------- | ---------------------------- |
| `cases`           | `idx_cases_created_at`                | `created_at`                 |
| `cases`           | `idx_cases_created_at_classification` | `created_at, classification` |
| `entities`        | `idx_entities_case_id`                | `case_id`                    |
| `intake_records`  | `idx_intake_records_created_at`       | `created_at`                 |
| `intake_records`  | `idx_intake_records_case_id`          | `case_id`                    |
| `intake_records`  | `idx_intake_records_victim_country`   | `victim_country`             |
| `indicator_stats` | `idx_indicator_stats_first_seen_at`   | `first_seen_at`              |
| `campaign_stats`  | `idx_campaign_stats_status`           | `status`                     |
| `campaign_stats`  | `idx_campaign_stats_risk_score`       | `risk_score`                 |

## BigQuery Migration Readiness (S6-16)

Per D2/Section 8.4, aggregation table schemas are designed for portability:

- `entity_stats`, `indicator_stats`, `campaign_stats`, `platform_kpis` use standard SQL types (TEXT, INTEGER, NUMERIC, TIMESTAMP)
- JSON columns (`entity_types`, `taxonomy_rollup`) map to BigQuery RECORD/STRUCT with schema extraction
- `platform_kpis` composite PK (`period_type`, `period_start`, `metric_name`) is compatible with BigQuery partitioning by `period_start`
- **Migration path:** Extract via `pg_dump` → transform JSON columns → load via `bq load` or Dataflow
- **Partition strategy:** Partition `platform_kpis` by `period_start` (monthly), cluster by `metric_name`
- **Status:** Schema is portable. Migration tooling deferred to production hardening phase.

## Recommendations

1. Add server-side response caching (Redis) for dashboard aggregate endpoints (TTL: 5 min)
2. Consider materialized views for loss-by-taxonomy and detection-velocity aggregations
3. Monitor query plans after index additions — verify index usage with `EXPLAIN ANALYZE`
