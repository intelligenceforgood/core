# Prepare Bootstrap Data Bundles

This guide explains how to build the golden data bundle required for bootstrapping.

Set a run date before starting:

```bash
export RUN_DATE=$(date +%Y%m%d)
```

## Build the Golden Bundle

The golden bundle consolidates all data sources into a single quality-filtered package. Three steps: ETL incident responses, generate seed SQL, consolidate.

### 1. ETL incident report responses

Export the [Incident Report (Responses) Google Sheet](https://docs.google.com/spreadsheets/d/1Aygqmpz_5LAwP7OZmm11AcZjIetvxJJ2xG6ms7_phvQ) as CSV, then place at `data/exports/incident_responses.csv`.

```bash
python scripts/etl/etl_incident_responses.py \
  --csv data/exports/incident_responses.csv \
  --output data/bundles/incident_responses/cases.jsonl
```

Extracts entities from indicator columns (wallet, URL, contact handles). Rejects rows with < 50 chars narrative.

### 2. Synthesize golden seed SQL

```bash
python scripts/etl/synthesize_golden_data.py \
  --output data/bundles/golden_seed/seed.sql
```

Generates SQL INSERTs for: 7 campaigns, 40 campaign-case links, 15 infrastructure edges, watchlist items + alerts, review queue entries, intake records across 15 countries. All `ON CONFLICT DO NOTHING`.

### 3. Build the consolidated bundle

```bash
i4g bootstrap build-golden-bundle \
  --bundles-dir data/bundles \
  --output-dir data/bundles/golden
```

Output: `data/bundles/golden/{cases.jsonl, seed.sql, manifest.json}`

Verify:

```bash
wc -l data/bundles/golden/cases.jsonl           # expect ~1200 records
python -m json.tool data/bundles/golden/manifest.json
grep -c 'INSERT INTO' data/bundles/golden/seed.sql   # expect ~100+ inserts
```

### 5. Upload to GCS (optional)

```bash
gsutil -m rsync -r data/bundles/golden gs://i4g-dev-data-bundles/$RUN_DATE/golden/
```

This allows other developers to bootstrap by setting `RUN_DATE` without rebuilding the bundle locally.

### 6. Run bootstrap

```bash
i4g bootstrap local reset
```

If the golden bundle exists in `data/bundles/golden/`, it is used automatically. No extra env vars needed.

### 7. Seed test engagements (optional)

After bootstrap completes, run the engagement seed script to create a
"Spring 2026 — UAB" engagement and assign the incident_responses cases:

```bash
sqlite3 data/i4g_store.db < scripts/sql/seed_engagement_spring_2026_uab.sql
```

For Cloud SQL (PostgreSQL), paste the contents of
`scripts/sql/seed_engagement_spring_2026_uab.sql` into the Cloud SQL Studio
query editor. The SQL is compatible with both SQLite and PostgreSQL.

This creates:

- An active engagement named "Spring 2026 — UAB" spanning the spring semester
- Assigns all ~56 incident_responses cases to the engagement
- Seeds 13 weekly/daily platform_kpis rows for immediate dashboard rendering

## Adding New Data Sources

1. Create an ETL script under `scripts/etl/` that reads the source and outputs JSONL
2. Output to `data/bundles/<source_name>/cases.jsonl`
3. Add the source to `_BUNDLE_SOURCES` in `scripts/build_golden_bundle.py`
4. Rebuild the golden bundle with step 3 above

All ETL scripts follow the same pattern: read input → normalize to `{case_id, text, entities, metadata}` → filter quality → write JSONL.
