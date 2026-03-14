# External Enrichment Cookbook

How to configure and troubleshoot passive DNS, ASN lookup, and takedown
verification enrichment sources.

## Passive DNS (SecurityTrails)

### Setup

1. Obtain an API key from [SecurityTrails](https://securitytrails.com/).
2. Set the environment variable:

   ```bash
   export I4G_ENRICHMENT__SECURITYTRAILS_API_KEY="your-api-key"
   ```

3. The enrichment service is available immediately — no restart required for
   worker jobs, but the API server requires a restart to pick up new settings.

### Usage

The passive DNS module provides two lookup functions:

- `lookup_domain(domain)` — returns A, AAAA, MX, NS records with first/last
  seen timestamps.
- `lookup_ip(ip)` — returns reverse DNS hostnames associated with the IP.

Both return a `PassiveDNSResult` dataclass. If the API key is missing, the
result contains an error message instead of records.

### Troubleshooting

| Symptom                 | Check                                                  |
| ----------------------- | ------------------------------------------------------ |
| "No API key configured" | Verify `I4G_ENRICHMENT__SECURITYTRAILS_API_KEY` is set |
| 403 Forbidden           | API key is invalid or rate-limited                     |
| Empty results           | Domain/IP has no historical DNS data in SecurityTrails |
| Timeout errors          | Check network connectivity to `api.securitytrails.com` |

## ASN Lookup (RDAP)

### Setup

No API key is required. The service uses the public RDAP bootstrap at
`rdap.org`.

### Usage

`lookup_ip(ip)` returns an `ASNInfo` dataclass with:

- `network_name` — registered network name
- `cidr` — IP prefix (e.g., `192.0.2.0/24`)
- `asn` — Autonomous System Number
- `asn_name` — AS organization name
- `country` — two-letter country code

### Troubleshooting

| Symptom              | Check                                       |
| -------------------- | ------------------------------------------- |
| Empty ASNInfo fields | IP is not in any registered network block   |
| Connection errors    | Check network connectivity to `rdap.org`    |
| Slow responses       | RDAP servers may throttle; consider caching |

## Takedown Verification

### Setup

Configure the job interval and batch size:

```bash
export I4G_ENRICHMENT__TAKEDOWN_CHECK_INTERVAL_HOURS=12
export I4G_ENRICHMENT__TAKEDOWN_MAX_URLS_PER_RUN=200
```

### How It Works

The takedown check job:

1. Selects URL entities from `entity_stats` where `taken_down_at` is NULL.
2. Sends an HTTP HEAD request to each URL.
3. Marks URLs as taken down if the response is 404, 410, 451, 502, 503, 521,
   or 523, or if the connection fails entirely.
4. Sets the `taken_down_at` timestamp on confirmed takedowns.

### Running Manually

```bash
conda run -n i4g i4g jobs takedown-check
```

### Troubleshooting

| Symptom                       | Check                                             |
| ----------------------------- | ------------------------------------------------- |
| URLs not marked as taken down | Site may still be responding with 200             |
| Too many false positives      | Temporary server errors; re-run after an interval |
| Job processes 0 URLs          | All URLs already have `taken_down_at` set         |

See `src/i4g/worker/jobs/takedown_check.py` and
`src/i4g/services/enrichment/` for the full implementation.
