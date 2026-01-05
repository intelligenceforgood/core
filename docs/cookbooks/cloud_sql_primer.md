# Cloud SQL Primer

This guide explains how to inspect, query, and manage permissions for the Cloud SQL (PostgreSQL) databases used by the i4g platform.

## Overview

The platform uses two distinct Cloud SQL instances per environment:

| Project | Environment | Instance Name | Database Name | Description |
| :--- | :--- | :--- | :--- | :--- |
| **App** | `dev` | `i4g-dev-db` | `i4g_db` | Main application database (cases, reviews, etc.) |
| **App** | `prod` | `i4g-prod-db` | `i4g_db` | Production application database |
| **PII Vault** | `dev` | `i4g-vault-dev-db` | `vault_db` | Isolated PII storage (tokens, secrets) |
| **PII Vault** | `prod` | `i4g-vault-prod-db` | `vault_db` | Production PII storage |

---

## 1. Connecting to the Database

You can connect to the database using either the **Cloud SQL Auth Proxy** (recommended for migrations and long sessions) or the **gcloud beta sql connect** command (recommended for quick ad-hoc tasks).

**Prerequisite:** For both methods, you must know the password for the user you are connecting as (usually `postgres` for admin tasks).

### Method A: Cloud SQL Auth Proxy (Recommended for Migrations)

This allows you to use standard tools (`psql`, DBeaver, Python scripts, Alembic) by forwarding a local port to the remote instance.

1.  **Start the Proxy**:
    Open a dedicated terminal and run:
    ```bash
    # Listen on port 5432 for Main DB and 5433 for Vault DB
    cloud-sql-proxy \
      i4g-dev:us-central1:i4g-dev-db?port=5432 \
      i4g-pii-vault-dev:us-central1:i4g-vault-dev-db?port=5433
    ```

2.  **Connect via psql**:
    In a separate terminal:
    ```bash
    # Connect to Main DB
    psql "host=127.0.0.1 port=5432 sslmode=disable user=postgres dbname=i4g_db"

    # Connect to Vault DB
    psql "host=127.0.0.1 port=5433 sslmode=disable user=postgres dbname=vault_db"
    ```

### Method B: gcloud beta sql connect (Quick Ad-hoc)

This command automatically starts a temporary proxy and connects via `psql`.

```bash
# Connect to Main DB
gcloud beta sql connect i4g-dev-db --user=postgres --quiet --project=i4g-dev

# Connect to Vault DB
gcloud beta sql connect i4g-vault-dev-db --user=postgres --quiet --project=i4g-pii-vault-dev
```

---

## 2. Schema Management (Re-initializing the DB)

If you need to reset the environment to a "virgin" state (e.g., during a full bootstrap reset), follow these steps.

### Step 1: Wipe the Databases

Connect to each database (using Method B is easiest here) and drop the schema/tables.

**Main DB (`i4g-dev-db`):**
```sql
-- Connect to i4g_db first
\c i4g_db

-- Drop and recreate the public schema
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO postgres;
GRANT ALL ON SCHEMA public TO public;
```

**Vault DB (`i4g-vault-dev-db`):**
```sql
-- Connect to vault_db first
\c vault_db

-- Drop tables individually (Vault doesn't use schemas as heavily)
DROP TABLE IF EXISTS pii_tokens CASCADE;
DROP TABLE IF EXISTS audit_log CASCADE;
DROP TABLE IF EXISTS alembic_version;
```

### Step 2: Apply Initial Schema (Alembic)

Use `alembic` locally to create the tables in the remote Cloud SQL instances. **You must have the Cloud SQL Proxy running (Method A).**

Run these commands from the `core/` directory:

```bash
# 1. Migrate Main DB (Port 5432)
ALEMBIC_DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:5432/i4g_db" \
alembic upgrade head

# 2. Migrate Vault DB (Port 5433)
# Note: Use the correct config file (alembic_vault.ini)
ALEMBIC_DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:5433/vault_db" \
alembic -c alembic_vault.ini upgrade head
```

*(Note: Replace `postgres:postgres` with your actual DB credentials if different.)*

---

## 3. Permission Management

After re-initializing the schema, you must ensure that the application service accounts have the correct permissions.

### Key Accounts

| Role | Account Email | Permissions Needed |
| :--- | :--- | :--- |
| **Admins** | `jerry@intelligenceforgood.org`<br>`gcp-i4g-admin@intelligenceforgood.org` | `ALL PRIVILEGES` on tables<br>`CREATE` on schema |
| **Service Accounts** | `sa-ingest@i4g-dev.iam`<br>`sa-app@i4g-dev.iam`<br>`sa-vault@i4g-pii-vault-dev.iam`<br>`sa-report@i4g-dev.iam` | `SELECT, INSERT, UPDATE, DELETE` |

### Granting Permissions

Run these commands as the `postgres` user (via `psql` or `gcloud sql connect`).

**Main DB (`i4g_db`):**
```sql
\c i4g_db

-- Grant Usage on Schema
GRANT USAGE ON SCHEMA public TO "sa-ingest@i4g-dev.iam";
GRANT USAGE ON SCHEMA public TO "sa-app@i4g-dev.iam";
GRANT USAGE ON SCHEMA public TO "sa-report@i4g-dev.iam";

-- Grant Table Access
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO "sa-ingest@i4g-dev.iam";
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO "sa-app@i4g-dev.iam";
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO "sa-report@i4g-dev.iam";

-- Grant Sequence Access (for auto-increment IDs)
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO "sa-ingest@i4g-dev.iam";
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO "sa-app@i4g-dev.iam";
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO "sa-report@i4g-dev.iam";
```

**Vault DB (`vault_db`):**
```sql
\c vault_db

-- Grant Table Access to Vault SA (Native Project)
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO "sa-vault@i4g-pii-vault-dev.iam";
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO "sa-vault@i4g-pii-vault-dev.iam";

-- Grant Table Access to App/Ingest SAs (Cross-Project Access from i4g-dev)
-- These accounts need to tokenize/detokenize PII
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO "sa-ingest@i4g-dev.iam";
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO "sa-ingest@i4g-dev.iam";

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO "sa-app@i4g-dev.iam";
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO "sa-app@i4g-dev.iam";
```

---

## 4. Common Queries

### Check Ingestion Status
```sql
SELECT run_id, dataset, status, case_count, sql_writes, created_at 
FROM ingestion_runs 
ORDER BY created_at DESC 
LIMIT 5;
```

### Check Deduplication
```sql
SELECT dataset, COUNT(*) as total_rows
FROM cases 
GROUP BY dataset;
```

### Deduplicate Source Documents
If `source_documents` has duplicate entries (same text/hash for the same case), use this to keep only the oldest record:

```sql
DELETE FROM source_documents
WHERE document_id IN (
    SELECT document_id
    FROM (
        SELECT
            document_id,
            ROW_NUMBER() OVER (
                PARTITION BY case_id, text_sha256
                ORDER BY created_at ASC
            ) as row_num
        FROM source_documents
        WHERE text_sha256 IS NOT NULL
    ) t
    WHERE t.row_num > 1
);
```

---

## 5. Troubleshooting

### "FATAL: database '...' does not exist"
Check the **Overview** table above. You might be connecting to `postgres` instead of `i4g_db` or `vault_db`.

### "FATAL: password authentication failed"
-   **IAM User:** Ensure your OAuth token is fresh (`gcloud auth print-access-token`).
-   **Postgres User:** Ensure you are using the password you just set.

### "Permission denied for table ..."
Follow the **Permission Management** section above to grant the missing privileges.
