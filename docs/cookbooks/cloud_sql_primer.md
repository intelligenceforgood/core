# Cloud SQL Primer

This guide explains how to inspect and query the Cloud SQL (PostgreSQL) database used by the i4g platform. It covers connecting via `gcloud`, using the Cloud SQL Auth Proxy for local tools, and common queries for verifying ingestion.

## Prerequisites

-   **Google Cloud SDK** installed and authenticated (`gcloud auth login`).
-   **PostgreSQL Client** (`psql`) installed locally (e.g., `brew install libpq` or `brew install postgresql`).
-   **Permissions**: You need `roles/cloudsql.client` and `roles/cloudsql.instanceUser` (or `roles/cloudsql.admin`) on the project.

## Connection Methods

### Method 1: Using `gcloud sql connect` (Quickest)

This method connects directly from your terminal using the `gcloud` wrapper. It handles the ephemeral certificate generation for you.

```bash
# Connect to the dev database
gcloud sql connect i4g-dev-db --user=ingest_user --database=i4g_db --project=i4g-dev
```

*   **Note**: You will be prompted for the password. You can retrieve it from Secret Manager:
    ```bash
    gcloud secrets versions access latest --secret="ingest-db-password" --project=i4g-dev
    ```

*   **Troubleshooting**: 
    *   If you see `FATAL: database "i4g_db" does not exist`, check the database name in the Terraform config (`infra/environments/app/dev/database.tf`). 
    *   If you see `FATAL: password authentication failed`, ensure you are using the latest secret version.
    *   If you see `HTTPError 403` and a warning about **impersonation**, try adding `--no-impersonate-service-account` to use your personal credentials:
        ```bash
        gcloud sql connect i4g-dev-db --user=ingest_user --database=i4g_db --project=i4g-dev --no-impersonate-service-account
        ```

### Method 2: Using Cloud SQL Auth Proxy (Recommended for GUI/Scripts)

The proxy allows you to connect using local tools (like DBeaver, pgAdmin, or local Python scripts) by forwarding a local port to the Cloud SQL instance.

1.  **Install the proxy** (if not already installed):
    ```bash
    brew install cloud-sql-proxy
    ```

2.  **Start the proxy**:
    ```bash
    # Forward local port 5432 to the instance
    cloud-sql-proxy i4g-dev:us-central1:i4g-dev-db
    ```
    *Leave this running in a separate terminal.*

3.  **Connect via `psql`**:
    ```bash
    # Retrieve password
    export DB_PASS=$(gcloud secrets versions access latest --secret="ingest-db-password" --project=i4g-dev)

    # Connect to localhost
    PGPASSWORD=$DB_PASS psql -h 127.0.0.1 -U ingest_user -d i4g_db
    ```

## Common Queries

Once connected, you can run standard SQL queries.

### 1. Check Ingestion Runs (Status & Counters)

This table tracks the status and counters for each ingestion job. **Crucially**, if `sql_writes` is high but the `cases` table count is low, it indicates heavy deduplication (see below).

```sql
SELECT run_id, dataset, status, case_count, sql_writes, vertex_writes, created_at 
FROM ingestion_runs 
ORDER BY created_at DESC 
LIMIT 5;
```

### 2. Verify Ingested Cases (Deduplication Check)

The `cases` table enforces a unique constraint on `(dataset, raw_text_sha256)`. If your source data contains many records with identical text (or empty text), they will be deduplicated into a single row per unique text content.

```sql
-- Count by dataset
SELECT dataset, COUNT(*) as total_rows
FROM cases 
GROUP BY dataset;
```

### 3. Inspect Recent Cases

View the most recently added cases to verify data integrity.

```sql
SELECT case_id, classification, confidence, created_at, dataset 
FROM cases 
ORDER BY created_at DESC 
LIMIT 5;
```

### 4. Check for Retries

If you suspect failures, check the `ingestion_retries` table (if applicable/implemented in your schema).

```sql
SELECT * FROM ingestion_retries LIMIT 10;
```

### 5. Diagnose Missing SQL Writes

If `sql_writes` is 0 in `ingestion_runs` but `case_count` is high, it means the SQL writer skipped the records. This usually happens if:
1.  **Empty Text**: The source record has no text content. Check logs for "Skipping SQL/Firestore fan-out... due to empty text".
2.  **SQL Disabled**: The `I4G_INGEST__ENABLE_SQL` environment variable is set to `false` (or defaults to false).
3.  **Writer Init Failure**: The SQL writer failed to initialize. Check logs for "SQL writer initialisation failed".
4.  **Bad Credentials**: If `I4G_STORAGE__CLOUDSQL_PASSWORD` is incorrect (e.g., set to the username `ingest_user` by mistake), the connection will fail, causing the writer initialization to fail.

### 6. Check `scam_records` (Structured Store)

The ingestion pipeline writes to two tables:
1.  `scam_records`: The primary "structured store" table (always written, even if text is empty).
2.  `cases`: The "dual-write" table (skipped if text is empty).

If `cases` is empty but `scam_records` has data, it confirms the **Empty Text** hypothesis.

```sql
SELECT count(*) FROM scam_records;
```

## Troubleshooting

### "FATAL: database 'i4g' does not exist"
Ensure you are connecting to the correct database name. In dev, it is typically `i4g_db`, not `i4g`.

### "FATAL: password authentication failed"
-   Verify you are using the correct user (`ingest_user` vs `postgres`).
-   Ensure you have the latest password from Secret Manager.

### "Connection refused" (Proxy)
-   Ensure the proxy is running.
-   Check if the instance is stopped or undergoing maintenance.
