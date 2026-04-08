# Looker Dashboard Templates

This directory contains LookML model definitions for the I4G cross-engagement
analytics Looker dashboards. They are designed to connect to the BigQuery
dataset exported by the `bq-export` job.

## Setup

1. **Run the BQ export job** to populate BigQuery:

   ```bash
   conda run -n i4g i4g jobs bq-export
   ```

2. **Create a Looker connection** named `i4g-analytics` pointing to the
   `i4g_analytics` dataset in your GCP project (`i4g-dev` or `i4g-prod`).

3. **Import these LookML files** into your Looker project:
   - `i4g_analytics.model.lkml` — model + explore definitions
   - `views/*.view.lkml` — dimension and measure definitions for each table
   - `dashboards/*.dashboard.lookml` — pre-built dashboard templates

4. **Set the `@{dataset}` constant** in your LookML project manifest to match
   your BigQuery dataset (e.g., `i4g-dev.i4g_analytics`).

## Tables Exported

| BigQuery Table             | Source                        | Description                                |
| -------------------------- | ----------------------------- | ------------------------------------------ |
| `engagements`              | `engagements` (Cloud SQL)     | Engagement metadata for join context       |
| `platform_kpis`            | `platform_kpis` (Cloud SQL)   | Daily/weekly KPIs with `engagement_id` dim |
| `entity_stats`             | `entity_stats` (Cloud SQL)    | Entity-level risk aggregates               |
| `indicator_stats`          | `indicator_stats` (Cloud SQL) | Indicator frequency and loss               |
| `campaign_stats`           | `campaign_stats` (Cloud SQL)  | Campaign risk scoring                      |
| `engagement_analyst_stats` | `engagement_analyst_stats`    | Per-analyst performance within engagements |

## Dashboard: Cross-Engagement Analytics

Pre-built dashboard (`dashboards/cross_engagement_analytics.dashboard.lookml`)
provides:

- **KPI summary cards** — total engagements, cases, loss, active analysts
- **Semester-over-semester trends** — cases and loss by engagement over time
- **University comparison** — cases, loss, and action rate by university
- **Analyst performance** — accuracy and participation by engagement
