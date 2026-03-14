# Partner Feed Monitoring Runbook

> Monitor partner API usage, troubleshoot feed issues, and configure rate limit alerts.

## Daily Health Check

Query `partner_feed_audit` for the last 24 hours:

```sql
SELECT partner_name,
       COUNT(*) AS requests,
       COUNT(CASE WHEN response_code = 200 THEN 1 END) AS success,
       COUNT(CASE WHEN response_code = 429 THEN 1 END) AS rate_limited,
       COUNT(CASE WHEN response_code >= 500 THEN 1 END) AS errors,
       SUM(result_count) AS total_indicators_served
FROM partner_feed_audit
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY partner_name
ORDER BY requests DESC;
```

## Key Metrics to Monitor

| Metric        | Alert Threshold                 | Action                                                          |
| ------------- | ------------------------------- | --------------------------------------------------------------- |
| 429 rate      | > 10% of requests               | Increase partner's `rate_limit_per_minute` or investigate abuse |
| 500 errors    | Any occurrence                  | Check server logs for database connectivity or query issues     |
| Zero requests | 48h silence from active partner | Contact partner, check key expiration                           |
| Unusual IP    | New IP for existing key         | Verify with partner, potential key compromise                   |

## Troubleshooting

### Partner Reports Empty Results

1. Check the `category` filter — verify indicator categories exist in `indicator_stats`
2. Check `minRiskScore` — high threshold may filter out all results
3. Verify aggregation tables are populated: `SELECT COUNT(*) FROM indicator_stats`

### Partner Receives 401

1. Verify key exists: `SELECT key_prefix, is_active, expires_at FROM partner_api_keys`
2. Check `is_active = true` and `expires_at` is in the future
3. Confirm partner is using `X-Partner-API-Key` header (not `Authorization`)

### Partner Receives 429

1. Check their `rate_limit_per_minute` setting
2. Review request patterns in `partner_feed_audit`
3. If legitimate usage, increase the limit

## Key Rotation

1. Create a new key with `is_active = true`
2. Distribute new key to partner
3. Set old key `is_active = false` after partner confirms migration
4. Do not delete old key — preserve audit trail
