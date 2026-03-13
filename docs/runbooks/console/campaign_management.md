# Console Runbook — Campaign Management

Operational guide for managing threat campaigns, including merge/split
procedures and auto-detection troubleshooting.

## Campaign lifecycle

| Status      | Description                                |
| ----------- | ------------------------------------------ |
| `detected`  | Auto-created by aggregation job            |
| `confirmed` | Analyst-verified campaign                  |
| `resolved`  | Threat mitigated, cases closed             |
| `archived`  | Historical reference, no active monitoring |

## Merge procedure

1. Navigate to **Intelligence → Campaigns**.
2. Open the target campaign detail page.
3. Click **Manage → Merge**.
4. Enter the campaign IDs to merge into this campaign.
5. Confirm. All linked cases transfer to the surviving campaign.

The merge is logged in the audit trail with the analyst username and timestamp.

## Split procedure

1. Open the campaign detail page.
2. Identify case IDs that do not belong (e.g., false entity overlap).
3. Click **Manage → Unlink** for each case to remove.
4. Unlinked cases are re-evaluated by the next aggregation run and may form a
   new campaign if sufficient entity overlap remains.

## Auto-detection troubleshooting

If campaigns are not being auto-detected:

1. **Aggregation job not running**: See the
   [Intelligence Dashboard runbook](intelligence_dashboard.md) for job health
   checks.
2. **Insufficient entity overlap**: Auto-detection requires at least 3 shared
   indicators across 2+ cases. Check `entity_stats` for overlapping
   `canonical_value` entries.
3. **All cases already assigned**: If every case is already linked to a
   campaign, the job will not create duplicates.

## Re-scoring campaigns

Campaign risk scores are recomputed on each aggregation run. To force an
immediate refresh:

```bash
conda run -n i4g I4G_PROJECT_ROOT=$PWD I4G_ENV=dev \
  i4g jobs analytics --force-refresh
```
