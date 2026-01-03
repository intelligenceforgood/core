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

## Connection Methods

You can connect to the database using either the **Cloud SQL Auth Proxy** (recommended for long sessions) or the **gcloud beta sql connect** command (recommended for quick ad-hoc tasks).

**Prerequisite:** For both methods, you must know the password for the user you are connecting as (usually `postgres` for admin tasks).

### Method A: Cloud SQL Auth Proxy (Standard)

This allows you to use standard tools (`psql`, DBeaver, Python scripts) by forwarding a local port to the remote instance.

1.  **Start the Proxy**:
    ```bash
    # For App Dev
    cloud-sql-proxy i4g-dev:us-central1:i4g-dev-db
    ```

2.  **Connect via psql**:
    ```bash
    # In a new terminal
    export PGPASSWORD=YOUR_POSTGRES_PASSWORD
    psql "host=127.0.0.1 port=5432 sslmode=disable user=postgres dbname=i4g_db"
    ```

### Method B: gcloud beta sql connect (Quick)

This command automatically starts a temporary proxy and connects via `psql`. It handles IPv6 networks correctly (unlike the standard `gcloud sql connect`).

```bash
# For App Dev
gcloud beta sql connect i4g-dev-db --user=postgres --quiet --project=i4g-dev
```

## User & Permission Management

While Terraform manages the infrastructure (instances, IAM users), **table-level permissions (GRANTS) must be applied manually** inside the database.

### Security Model

*   **Schema Ownership**: Ideally, the `postgres` superuser (or a dedicated admin role) should own all tables.
*   **Service Accounts**: Runtime identities (`sa-app`, `sa-ingest`, `sa-report`) should be granted specific privileges (`SELECT`, `INSERT`, `UPDATE`, `DELETE`) but should **not** own the tables.

### Key Accounts

| Role | Account Email | Permissions Needed |
| :--- | :--- | :--- |
| **Admins** | `jerry@intelligenceforgood.org`<br>`gcp-i4g-admin@intelligenceforgood.org` | `ALL PRIVILEGES` on tables<br>`CREATE` on schema |
| **Analysts** | `gcp-i4g-analyst@intelligenceforgood.org` | `SELECT` (Read-only) |
| **Service Accounts** | `sa-ingest@i4g-dev.iam`<br>`sa-app@i4g-dev.iam`<br>`sa-vault@i4g-pii-vault-dev.iam`<br>`sa-report@i4g-dev.iam` | `SELECT, INSERT, UPDATE, DELETE` |

*Note: Service Account usernames in Postgres are the email **without** `.gserviceaccount.com`.*

## Cookbook: Managing Permissions

### 1. The "Fix Permissions" Script

If a service account (e.g., `sa-report`) gets "Permission Denied", run these commands as `postgres`.

**Standard Procedure**

All application tables **must be owned by the `postgres` user**. This ensures consistent permission management.

```sql
\c i4g_db

-- Grant Usage
GRANT USAGE ON SCHEMA public TO "sa-report@i4g-dev.iam";

-- Grant Data Access
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO "sa-report@i4g-dev.iam";
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO "sa-report@i4g-dev.iam";
```

### 2. Automating Ownership (Recommended)

To ensure tables created by applications (e.g., `sa-app`, `sa-ingest`) are automatically owned by `postgres`, these service accounts must be granted the `postgres` role. This allows them to execute `SET ROLE postgres` before creating tables.

**Run the helper script:**

```bash
# From the infra/ directory
./scripts/grant_postgres_role.sh dev
```

**Or manually:**

```sql
GRANT postgres TO "sa-app@i4g-dev.iam";
GRANT postgres TO "sa-ingest@i4g-dev.iam";
GRANT postgres TO "sa-intake@i4g-dev.iam";
```

### 3. Fixing Incorrect Ownership

If a table was accidentally created by a service account (e.g., `sa-app`) instead of `postgres` (because the above grant was missing), you must reassign ownership to `postgres`.

```sql
\c i4g_db

-- 1. Allow postgres to impersonate the current owner (e.g., sa-app)
GRANT "sa-app@i4g-dev.iam" TO postgres;

-- 2. Reassign ownership of all objects owned by the SA to postgres
REASSIGN OWNED BY "sa-app@i4g-dev.iam" TO postgres;
```

### 3. Verifying Access

To check if a user (e.g., `sa-report` or `jerry@intelligenceforgood.org`) is missing access to any tables:

```sql
SELECT t.tablename AS "Missing Access To"
FROM pg_tables t
LEFT JOIN information_schema.role_table_grants g
  ON t.tablename = g.table_name
  AND g.grantee = 'jerry@intelligenceforgood.org'
  AND g.table_schema = 'public'
WHERE t.schemaname = 'public'
  AND g.table_name IS NULL;
```

*   **0 rows**: All good.
*   **Rows returned**: The user cannot access these tables.

## Common Queries

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

## Troubleshooting

### "FATAL: database '...' does not exist"
Check the **Overview** table above. You might be connecting to `postgres` instead of `i4g_db` or `vault_db`.

### "FATAL: password authentication failed"
-   **IAM User:** Ensure your OAuth token is fresh (`gcloud auth print-access-token`).
-   **Postgres User:** Ensure you are using the password you just set.

### "Permission denied for table ..."
Follow the **Bootstrapping Permissions** section above to grant the missing privileges.
