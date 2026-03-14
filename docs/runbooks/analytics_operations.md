# Analytics Operations Runbook

> Operational procedures for the TIFAP analytics pipeline, aggregation jobs, and external enrichments.

## Aggregation Job Health

### Monitoring Stats Freshness

Check `platform_kpis` for the latest `updated_at` timestamp:

```sql
SELECT metric_name, MAX(period_start) AS latest_period, updated_at
FROM platform_kpis
GROUP BY metric_name, updated_at
ORDER BY updated_at DESC
LIMIT 10;
```

If `updated_at` is older than 24 hours for daily metrics, the aggregation job may have stalled.

### Running the Aggregation Job Manually

```bash
conda run -n i4g I4G_PROJECT_ROOT=$PWD I4G_ENV=dev i4g jobs analytics refresh
```

### Common Issues

| Symptom                            | Likely Cause                      | Fix                                        |
| ---------------------------------- | --------------------------------- | ------------------------------------------ |
| Dashboard shows stale KPIs         | Aggregation job not running       | Check Cloud Run job schedule, run manually |
| Entity stats missing for new cases | Cases ingested but not aggregated | Run `i4g jobs analytics refresh`           |
| Campaign stats out of sync         | New cases not linked to campaigns | Check `threat_campaign_cases` table        |

## External Enrichment API Health

### Blockchain Analytics

```bash
# Test mock vendor locally
conda run -n i4g python -c "from i4g.services.enrichment.blockchain import enrich_wallet; print(enrich_wallet('0xtest', vendor='mock'))"
```

For production vendor (Chainalysis/TRM/Elliptic), verify API key is set:

```bash
echo $I4G_ENRICHMENT__BLOCKCHAIN_API_KEY | head -c 8
```

### Passive DNS / ASN Lookup

```bash
conda run -n i4g python -c "from i4g.services.enrichment.passive_dns import lookup_domain; print(lookup_domain('example.com'))"
```

## Performance Troubleshooting

### Slow Dashboard Queries

1. Check if new indexes exist: `idx_cases_created_at`, `idx_intake_records_created_at`
2. Run `EXPLAIN ANALYZE` on the slow query
3. Verify aggregation tables (`entity_stats`, `indicator_stats`) are populated

### Large Graph Rendering

- Graphs with > 500 nodes may be slow to render
- Use the cluster detection feature to collapse groups
- Consider filtering by entity type or time range

## BigQuery Migration Procedure

When migrating from PostgreSQL to BigQuery:

1. Export aggregation tables via `pg_dump` with `--data-only --table=entity_stats,indicator_stats,campaign_stats,platform_kpis`
2. Transform JSON columns to structured records using a migration script
3. Load via `bq load --source_format=NEWLINE_DELIMITED_JSON`
4. Partition `platform_kpis` by `period_start`, cluster by `metric_name`
5. Update `I4G_STORAGE__STRUCTURED_BACKEND` to `bigquery`

## Partner Feed Monitoring

Monitor the `partner_feed_audit` table for unusual patterns:

```sql
SELECT partner_name, COUNT(*) AS request_count,
       AVG(result_count) AS avg_results,
       MIN(created_at) AS first_request,
       MAX(created_at) AS last_request
FROM partner_feed_audit
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY partner_name;
```

See `core/docs/runbooks/console/partner_feed_monitoring.md` for detailed monitoring procedures.
