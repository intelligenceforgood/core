# Prepare Bootstrap Data Bundles

This guide explains how to generate, export, and upload the data bundles required for bootstrapping the local and dev environments.

Before generating artifacts, set a run date and reuse `$RUN_DATE` everywhere the instructions reference timestamped folders so the exports stay in sync:
```bash
export RUN_DATE=$(date +%Y%m%d)
```
The bootstrap flow expects three bundles staged in the versioned bucket `gs://i4g-dev-data-bundles/` (or the project-specific bucket you pass via `--bundle-uri`). Use timestamped subfolders keyed by `$RUN_DATE` to keep versions (for example `synthetic_coverage/$RUN_DATE/`).

## Synthetic coverage bundle (generate locally, then upload)
1) Generate artifacts (full set by default; add `--smoke` for the small slice):
  ```bash
  i4g bootstrap generate-coverage \
    --output-dir data/bundles/synthetic_coverage/full \
    --seed 1337
  ```
  - Optional: `--include wallet_verification romance_pretext ...` to restrict scenarios; `--total-count` to fix total rows.
2) Build a manifest with hashes/counts:
  ```bash
  i4g bootstrap bundle-manifest \
    --bundle-dir data/bundles/synthetic_coverage/full \
    --bundle-id synthetic_coverage \
    --provenance "synthetic coverage seed=1337" \
    --license CC0 \
    --tag synthetic --tag coverage --no-pii
  ```
3) Publish to GCS (example versioned path):
  ```bash
  gsutil -m rsync -r data/bundles/synthetic_coverage/full gs://i4g-dev-data-bundles/synthetic_coverage/$RUN_DATE/full
  ```
  - For the smoke slice, rerun step 1 with `--smoke` and upload to `.../synthetic_coverage_smoke/$RUN_DATE/`.
4) Use the uploaded manifest path as `--bundle-uri` when running `i4g bootstrap ...`.

## Legacy Azure export bundle (rebuild from Azure, then upload)
Prereqs: access to Azure SQL, Blob Storage, and Cognitive Search plus GCP auth to write to the target bucket. Run from repo root in the `i4g` Conda env.

Review the [Azure legacy data primer](azure_legacy_data.md) for the environment variables, credentials, and CLI recipes you use in this flow.

1) Prepare the bucket prefixes so the Azure container copy command has a destination.
  ```bash
  gsutil -m cp -n /dev/null gs://i4g-dev-data-bundles/legacy_azure/$RUN_DATE/forms/.keep || true
  gsutil -m cp -n /dev/null gs://i4g-dev-data-bundles/legacy_azure/$RUN_DATE/groupsio/.keep || true
  ```
2) Copy Azure Blob containers into GCS (use `--dry-run` first, then rerun without it; add `--overwrite` when replacing existing objects). The Azure Functions in `dtp/IFG-AzureFunctions` still target `intake-form-attachments` and `groupsio-attachments`—so point the container flags at those buckets.
  ```bash
  i4g azure azure-blob-to-gcs -- \
    --connection-string "$AZURE_STORAGE_CONNECTION_STRING" \
    --container intake-form-attachments=gs://i4g-dev-data-bundles/legacy_azure/$RUN_DATE/forms \
    --container groupsio-attachments=gs://i4g-dev-data-bundles/legacy_azure/$RUN_DATE/groupsio \
    --dry-run
  ```
  ```bash
  i4g azure azure-blob-to-gcs -- \
    --connection-string "$AZURE_STORAGE_CONNECTION_STRING" \
    --container intake-form-attachments=gs://i4g-dev-data-bundles/legacy_azure/$RUN_DATE/forms \
    --container groupsio-attachments=gs://i4g-dev-data-bundles/legacy_azure/$RUN_DATE/groupsio
  ```
  If you are unsure which containers are populated, use the `az storage container list` loop from [docs/cookbooks/azure_legacy_data.md](docs/cookbooks/azure_legacy_data.md#L54-L80) to inspect each attachment account before re-running the script.
  The legacy code under [dtp/IFG-AzureFunctions/utilities/groupsio_transfer/att_transfer.py](dtp/IFG-AzureFunctions/utilities/groupsio_transfer/att_transfer.py#L9-L40) still reads from `groupsio-attachments`, and [dtp/IFG-AzureFunctions/process_intake_forms/config.py](dtp/IFG-AzureFunctions/process_intake_forms/config.py#L1-L25) defines `CONTAINER_NAME = 'intake-form-attachments'`, so these are the canonical names the migration helpers expect.

3) Mirror the container exports into your local bundle staging area so you can package everything together later:
  ```bash
  mkdir -p data/bundles/legacy_azure/$RUN_DATE
  gsutil -m rsync -r gs://i4g-dev-data-bundles/legacy_azure/$RUN_DATE/forms data/bundles/legacy_azure/$RUN_DATE/forms
  gsutil -m rsync -r gs://i4g-dev-data-bundles/legacy_azure/$RUN_DATE/groupsio data/bundles/legacy_azure/$RUN_DATE/groupsio
  ```

4) Export Azure SQL intake tables to Firestore staging.

  **Recommended: Use the helper script (Azure AD Auth)**
  This method uses your active `az login` session and avoids password complexity issues.
  ```bash
  # 1. Set up environment variables (edit the template first if needed)
  source scripts/migration/env_template.sh

  # 2. Run the migration using the helper script
  ./scripts/migration/run_migration.sh
  ```

  **Alternative: Manual Execution**
  ```bash
  # Ensure AZURE_SQL_CONNECTION_STRING is set (via env_template.sh)
  i4g azure azure-sql-to-firestore -- --firestore-project i4g-dev --use-aad
  ```

  **Troubleshooting: Password Authentication**
  If you must use SQL authentication and encounter "Login failed" or password policy errors, use the reset tool to force a clean state for the `migration_user`:
  ```bash
  # Reset the user to a fresh state with a known password
  python scripts/migration/reset_sql_user.py "YourStrongPassword123!"
  
  # Then export the password and run the fix script
  export SQL_MIGRATION_PASSWORD="YourStrongPassword123!"
  ./scripts/migration/fix_and_run.sh
  ```

  - Tables covered: `intake_form_data`, `intake_form_data_last_processed`, `groupsio_message_data`; adjust with `--tables` if needed.
5) Export Azure Cognitive Search indexes, then transform for Vertex:
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
  - Copy the Vertex-ready exports into the bundle folder so they travel with the blob data:
    ```bash
    rsync -a data/search_exports/$RUN_DATE/vertex data/bundles/legacy_azure/$RUN_DATE/search_exports
    ```
6) Build the legacy bundle and manifest (include the staged blobs, search exports, and SQL/report artifacts you generated):
  ```bash
  i4g bootstrap bundle-manifest \
    --bundle-dir data/bundles/legacy_azure/$RUN_DATE \
    --bundle-id legacy_azure \
    --provenance "azure export $RUN_DATE" \
    --license "restricted" \
    --tag legacy --tag azure --pii
  ```
  - The manifest command writes `manifest.generated.json` into the bundle directory and hashes every asset you staged.
7) Publish the completed bundle to GCS so downstream bootstrap runs can reference it:
  ```bash
  gsutil -m rsync -r data/bundles/legacy_azure/$RUN_DATE gs://i4g-dev-data-bundles/legacy_azure/$RUN_DATE/
  ```
  The upload includes `manifest.generated.json` (along with the blobs, search exports, and reports). Point `--bundle-uri` at that file (`gs://i4g-dev-data-bundles/legacy_azure/$RUN_DATE/manifest.generated.json`) to match the manifest the pipeline produces; the helper stages exactly what you uploaded before rebuilding the sandbox.

## Public/third-party scam bundle (recreate from upstream sources)
Sources and licenses are listed in [docs/development/bundle_sources_and_coverage.md](docs/development/bundle_sources_and_coverage.md). Keep PII-free and honor licensing.

1) Fetch upstream corpora into a working dir (example uses UCI SMS Spam Collection and SpamAssassin):
  ```bash
  mkdir -p data/bundles/public_scams/$RUN_DATE/raw
  curl -L https://archive.ics.uci.edu/ml/machine-learning-databases/00228/smsspamcollection.zip \
    -o data/bundles/public_scams/$RUN_DATE/raw/smsspamcollection.zip
  curl -L https://spamassassin.apache.org/old/publiccorpus/20030228_spam.tar.bz2 \
    -o data/bundles/public_scams/$RUN_DATE/raw/spamassassin_spam.tar.bz2
  ```
2) Convert to JSONL for ingestion (keeps text + label; extend as needed):
  ```bash
  python - <<'PY'
  import json, pathlib, zipfile, tarfile

  root = pathlib.Path("data/bundles/public_scams/$RUN_DATE")
  out = root / "cases.jsonl"
  out.parent.mkdir(parents=True, exist_ok=True)
  out.write_text("", encoding="utf-8")

  with out.open("a", encoding="utf-8") as sink:
    # UCI SMS
    with zipfile.ZipFile(root / "raw/smsspamcollection.zip") as zf:
      with zf.open("SMSSpamCollection") as fh:
        for idx, line in enumerate(fh):
          label, text = line.decode("utf-8", errors="ignore").split("\t", 1)
          rec = {
            "id": f"uci_sms_{idx}",
            "dataset": "public_scams",
            "source": "uci_sms",
            "label": label,
            "text": text.strip(),
            "pii": False,
          }
          sink.write(json.dumps(rec) + "\n")

    # SpamAssassin spam set
    with tarfile.open(root / "raw/spamassassin_spam.tar.bz2") as tf:
      for member in tf.getmembers():
        if member.isdir():
          continue
        content = tf.extractfile(member).read().decode("latin-1", errors="ignore")
        rec = {
          "id": f"sa_{member.name}",
          "dataset": "public_scams",
          "source": "spamassassin",
          "label": "spam",
          "text": content.strip(),
          "pii": False,
        }
        sink.write(json.dumps(rec) + "\n")
  PY
  ```
3) Build the manifest and upload:
  ```bash
  i4g bootstrap bundle-manifest \
    --bundle-dir data/bundles/public_scams/$RUN_DATE \
    --bundle-id public_scams \
    --provenance "public corpora refresh $RUN_DATE" \
    --license "see sources" \
    --tag public --tag scams --no-pii

  gsutil -m rsync -r data/bundles/public_scams/$RUN_DATE gs://i4g-dev-data-bundles/public_scams/$RUN_DATE
  ```
4) Reference the uploaded manifest as `--bundle-uri` when bootstrapping.
