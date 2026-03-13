# Console Runbook — Intelligence Dashboard

Operational guide for monitoring the Intelligence Dashboard and its data
freshness.

## Prerequisites

- Access to the GCP project hosting the Cloud SQL instance.
- `analyst` or `admin` role in the i4g console.

## Monitoring the aggregation job

The analytics aggregation job runs every 15 minutes (configurable via
`I4G_ANALYTICS__REFRESH_INTERVAL_MINUTES`). Verify it is running:

```bash
# Check Cloud Run job executions
gcloud run jobs executions list --job=analytics-aggregation --region=us-central1
```

### Verifying stats freshness

Query the latest `platform_kpis` row to confirm aggregation recency:

```sql
SELECT period_start, total_cases, total_loss
FROM platform_kpis
ORDER BY period_start DESC
LIMIT 1;
```

If the most recent `period_start` is more than 30 minutes stale, investigate
the job logs.

## Troubleshooting stale data

1. **Job not running**: Check Cloud Scheduler trigger status. Re-enable if
   paused.
2. **Job failing**: Inspect Cloud Run logs for the aggregation job:
   ```bash
   gcloud run jobs executions describe <exec-id> --region=us-central1
   ```
3. **Database lock contention**: The aggregation job uses upserts. If another
   long-running write holds locks, the job may time out. Check
   `pg_stat_activity` for blocking queries.
4. **Missing source data**: If `entity_stats` or `indicator_stats` are empty,
   verify that the linkage extraction job has run at least once.

## LEA referral suggestions

The Intelligence Dashboard surfaces LEA referral suggestions for entities and
campaigns exceeding risk thresholds. If suggestions are not appearing:

- Verify `entity_stats` contains rows with `risk_score > 0`.
- Confirm `case_count >= 5` and `total_loss >= 50000` for at least one entity.
- Check that the `/intelligence/lea-suggestions` endpoint returns data.
