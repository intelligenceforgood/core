# Watchlist Alerts — Operations Runbook

Procedures for monitoring watchlist job health, triaging alerts, and
resolving common issues.

## Job Health Check

The watchlist check job runs every 30 minutes by default. Verify it is
running:

```bash
# Check recent job executions (Cloud Run)
gcloud run jobs executions list --job=watchlist-check --region=us-central1 --limit=5

# Check local logs
conda run -n i4g i4g jobs watchlist-check
```

## Alert Triage

### Viewing Unread Alerts

```bash
# API call
curl -H "Authorization: Bearer $TOKEN" \
  "$API_URL/intelligence/watchlist/alerts?is_read=false"
```

### Alert Types

| Type             | Meaning                                                |
| ---------------- | ------------------------------------------------------ |
| `new_activity`   | The entity appeared in new cases since last check      |
| `loss_threshold` | The entity's cumulative loss exceeds the set threshold |

### Marking Alerts as Read

```bash
# Single alert
curl -X POST "$API_URL/intelligence/watchlist/alerts/{alert_id}/read" \
  -H "Authorization: Bearer $TOKEN"

# All alerts
curl -X POST "$API_URL/intelligence/watchlist/alerts/read-all" \
  -H "Authorization: Bearer $TOKEN"
```

## Common Issues

### Alerts Not Generating

1. **Job not running** — check Cloud Scheduler / cron trigger is active.
2. **No watchlist items** — verify items exist via
   `GET /intelligence/watchlist/items`.
3. **Entity not in entity_stats** — the analytics aggregation job must run
   first to populate `entity_stats`.
4. **Baseline already current** — the job tracks a `[baseline:N]` tag in
   the item's note field. If the baseline matches the current case count,
   no alert fires.

### Duplicate Alerts

The job deduplicates alerts by checking existing unread alerts for the same
watchlist item. If duplicates appear, check for concurrent job executions
(only one instance should run at a time).

### Stale Baselines

If an item's baseline is wrong, update the note field to reset it:

```bash
curl -X PUT "$API_URL/intelligence/watchlist/items/{item_id}" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"note": "Reset baseline [baseline:0]"}'
```

## Configuration Reference

| Env Var                                           | Default | Description             |
| ------------------------------------------------- | ------- | ----------------------- |
| `I4G_ANALYTICS__WATCHLIST_CHECK_INTERVAL_MINUTES` | 30      | Job execution frequency |
