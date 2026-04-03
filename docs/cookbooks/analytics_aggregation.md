# Analytics Aggregation Cookbook

## Running Aggregation Manually

The analytics aggregation job computes materialized statistics from raw case
and entity data. Run it locally:

```bash
conda run -n i4g I4G_PROJECT_ROOT=$PWD I4G_ENV=dev I4G_LLM__PROVIDER=mock \
  i4g jobs analytics-aggregate
```

Or via the backfill framework:

```bash
i4g backfill run analytics
```

On Cloud Run:

```bash
gcloud run jobs execute analytics-aggregation-job \
  --project i4g-dev \
  --region us-central1
```

## Output Tables

The job refreshes four materialized tables:

| Table             | Primary Key                      | Purpose                                        |
| ----------------- | -------------------------------- | ---------------------------------------------- |
| `entity_stats`    | `(entity_type, canonical_value)` | Per-entity risk, loss totals, lifecycle status |
| `indicator_stats` | `indicator_id`                   | Indicator freshness, case counts, eCX status   |
| `campaign_stats`  | `campaign_id`                    | Campaign-level aggregates and risk score       |
| `platform_kpis`   | `(period_type, period_start)`    | Daily/weekly KPI snapshots                     |

## Entity Lifecycle Statuses

The aggregation job computes entity lifecycle statuses based on case activity:

| Status        | Rule                                                      |
| ------------- | --------------------------------------------------------- |
| **active**    | Last seen within 14 days and at least one open case.      |
| **declining** | Last seen 14–29 days ago.                                 |
| **dormant**   | Last seen 30+ days ago.                                   |
| **resolved**  | No open cases remain.                                     |
| **flagged**   | Analyst-set, sticky — never auto-transitioned by the job. |

Campaign statuses follow a parallel lifecycle: `emerging → active → declining → dormant → closed`.

## Verifying Stats

After aggregation, verify the output tables:

```sql
-- Check entity_stats row counts by type and status
SELECT entity_type, status, COUNT(*)
FROM entity_stats
GROUP BY entity_type, status
ORDER BY entity_type, status;

-- Check KPI freshness
SELECT period_type, MAX(period_start) AS latest
FROM platform_kpis
GROUP BY period_type;

-- Check campaign stats
SELECT status, COUNT(*), SUM(case_count) AS total_cases
FROM campaign_stats
GROUP BY status;

-- Check indicator stats
SELECT COUNT(*) AS total, MAX(updated_at) AS last_refresh
FROM indicator_stats;
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

1. Raw data lives in `cases`, `intake_records`, `entities`, `indicators`,
   `threat_campaigns`, and `threat_campaign_cases` tables.
2. The aggregation job reads raw data and writes to:
   - `entity_stats` — per-entity metrics (case count, risk score, lifecycle status, loss totals).
   - `indicator_stats` — per-indicator metrics (case count, loss, eCX status).
   - `campaign_stats` — per-campaign metrics (case count, risk score, campaign status).
   - `platform_kpis` — daily and weekly KPI snapshots (total cases, loss, new indicators/entities).
3. API endpoints read from materialized tables for fast query response.

## Active Threats Metric

The Impact Dashboard's "Active Threats" KPI counts entities from `entity_stats`
where `status = 'active'` AND `entity_type` is one of the 14 threat entity
types (defined in `src/i4g/utils/entity_types.py:THREAT_ENTITY_TYPES`).
Contextual NER types (person, organization, location) are excluded.

## Relationship with Backfill Framework

The analytics task is also registered in the backfill framework. Running
`i4g backfill run analytics` invokes the same aggregation logic. The backfill
daemon includes analytics in its continuous processing loop. See
[Backfill Framework](backfill_framework.md) for details.
