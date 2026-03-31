# Prepare Bootstrap Data Bundles

This guide explains how to build the golden data bundle required for bootstrapping.

Set a run date before starting:

```bash
export RUN_DATE=$(date +%Y%m%d)
```

## Build the Golden Bundle

The golden bundle consolidates all data sources into a single quality-filtered package. Four steps: clean legacy data, ETL incident responses, generate seed SQL, consolidate.

### 1. Download and clean legacy Azure data

Download the legacy Azure bundle from GCS (one-time, ~15 min):

```bash
mkdir -p data/bundles/legacy_azure
gsutil -m rsync -r gs://i4g-dev-data-bundles/2025-12-17/legacy_azure data/bundles/legacy_azure
```

Run the cleaning script:

```bash
python scripts/etl/clean_legacy_azure.py \
  --input data/bundles/legacy_azure \
  --output data/bundles/legacy_azure_clean/cases.jsonl
```

Filters: min 50-char text, SHA-256 dedup, drops malformed records. Expect ~50% duplicate skip rate (the GCS bundle contains duplicate JSONL paths).

### 2. ETL incident report responses

Export the [Incident Report (Responses) Google Sheet](https://docs.google.com/spreadsheets/d/1Aygqmpz_5LAwP7OZmm11AcZjIetvxJJ2xG6ms7_phvQ) as CSV, then place at `data/exports/incident_responses.csv`.

```bash
python scripts/etl/etl_incident_responses.py \
  --csv data/exports/incident_responses.csv \
  --output data/bundles/incident_responses/cases.jsonl
```

Extracts entities from indicator columns (wallet, URL, contact handles). Rejects rows with < 50 chars narrative.

### 3. Synthesize golden seed SQL

```bash
python scripts/etl/synthesize_golden_data.py \
  --output data/bundles/golden_seed/seed.sql
```

Generates SQL INSERTs for: 7 campaigns, 40 campaign-case links, 15 infrastructure edges, watchlist items + alerts, review queue entries, intake records across 15 countries. All `ON CONFLICT DO NOTHING`.

### 4. Build the consolidated bundle

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

## Adding New Data Sources

1. Create an ETL script under `scripts/etl/` that reads the source and outputs JSONL
2. Output to `data/bundles/<source_name>/cases.jsonl`
3. Add the source to `_BUNDLE_SOURCES` in `scripts/build_golden_bundle.py`
4. Rebuild the golden bundle with step 4 above

All ETL scripts follow the same pattern: read input → normalize to `{case_id, text, entities, metadata}` → filter quality → write JSONL.

## Reference: Legacy Azure Export (Historical)

> This section documents the full Azure-to-GCS export process. You only need this if re-exporting from Azure — the golden bundle already includes cleaned legacy Azure data.

Prereqs: access to Azure SQL, Blob Storage, and Cognitive Search plus GCP auth. See [Azure legacy data primer](azure_legacy_data.md) for credentials and CLI recipes.

<details>
<summary>Expand legacy Azure export steps</summary>

1. Prepare GCS bucket prefixes:

   ```bash
   gsutil -m cp -n /dev/null gs://i4g-dev-data-bundles/legacy_azure/$RUN_DATE/forms/.keep || true
   gsutil -m cp -n /dev/null gs://i4g-dev-data-bundles/legacy_azure/$RUN_DATE/groupsio/.keep || true
   ```

2. Copy Azure Blob containers to GCS:

   ```bash
   i4g azure azure-blob-to-gcs -- \
     --connection-string "$AZURE_STORAGE_CONNECTION_STRING" \
     --container intake-form-attachments=gs://i4g-dev-data-bundles/legacy_azure/$RUN_DATE/forms \
     --container groupsio-attachments=gs://i4g-dev-data-bundles/legacy_azure/$RUN_DATE/groupsio
   ```

3. Mirror to local staging:

   ```bash
   mkdir -p data/bundles/legacy_azure/$RUN_DATE
   gsutil -m rsync -r gs://i4g-dev-data-bundles/legacy_azure/$RUN_DATE/forms data/bundles/legacy_azure/$RUN_DATE/forms
   gsutil -m rsync -r gs://i4g-dev-data-bundles/legacy_azure/$RUN_DATE/groupsio data/bundles/legacy_azure/$RUN_DATE/groupsio
   ```

4. Export Azure SQL intake tables:

   ```bash
   source scripts/migration/env_template.sh
   ./scripts/migration/run_migration.sh
   ```

5. Export Azure Cognitive Search indexes:

   ```bash
   i4g azure azure-search-export -- \
     --endpoint "$AZURE_SEARCH_ENDPOINT" \
     --admin-key "$AZURE_SEARCH_ADMIN_KEY" \
     --indexes intake-form-search groupsio-search \
     --output-dir data/search_exports/$RUN_DATE
   i4g azure azure-search-to-vertex -- \
     --input-dir data/search_exports/$RUN_DATE \
     --output-dir data/search_exports/$RUN_DATE/vertex \
     --index intake-form-search groupsio-search
   ```

6. Build manifest and publish:
   ```bash
   i4g bootstrap bundle-manifest \
     --bundle-dir data/bundles/legacy_azure/$RUN_DATE \
     --bundle-id legacy_azure \
     --provenance "azure export $RUN_DATE" \
     --license "restricted" \
     --tag legacy --tag azure --pii
   gsutil -m rsync -r data/bundles/legacy_azure/$RUN_DATE gs://i4g-dev-data-bundles/legacy_azure/$RUN_DATE/
   ```

</details>
