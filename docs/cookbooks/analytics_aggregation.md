# Analytics Aggregation Cookbook

## Running Aggregation Manually

The analytics aggregation job computes materialized statistics from raw case
and entity data. Run it locally:

```bash
conda run -n i4g I4G_PROJECT_ROOT=$PWD I4G_ENV=dev I4G_LLM__PROVIDER=mock \
  i4g jobs analytics-aggregate
```

On Cloud Run:

```bash
gcloud run jobs execute analytics-aggregation-job \
  --project i4g-dev \
  --region us-central1
```

## Verifying Stats

After aggregation, verify the output tables:

```sql
-- Check entity_stats row counts
SELECT entity_type, COUNT(*) FROM entity_stats GROUP BY entity_type;

-- Check KPI freshness
SELECT MAX(period_end) FROM analytics_kpis;

-- Check monthly KPI rows
SELECT COUNT(*) FROM analytics_kpis_monthly;
```

## Troubleshooting Stale Data

If the Timeline, Taxonomy Explorer, or Geographic Heatmap show stale data:

1. Check when aggregation last ran:
   ```bash
   gcloud run jobs executions list --job analytics-aggregation-job \
     --project i4g-dev --region us-central1 --limit 5
   ```
2. Verify the job succeeded (exit code 0).
3. If it failed, check logs for SQL errors or connection timeouts.
4. Re-run the job manually using the command above.

## Configuring Refresh Interval

The aggregation job runs on a Cloud Scheduler cron. Adjust the schedule:

```bash
gcloud scheduler jobs update http analytics-aggregation-trigger \
  --project i4g-dev \
  --schedule "0 */4 * * *"  # Every 4 hours
```

For development, you can run the job on-demand. In production, the default
schedule is every 6 hours.

## Data Flow

1. Raw data lives in `cases`, `intake_records`, `entity_links` tables.
2. The aggregation job reads raw data and writes to:
   - `entity_stats` — per-entity metrics (case count, risk score, status).
   - `analytics_kpis` — weekly KPI snapshots.
   - `analytics_kpis_monthly` — monthly KPI snapshots.
3. API endpoints read from materialized tables for fast query response.
