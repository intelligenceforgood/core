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

## Connection (Cloud SQL Proxy)

We recommend using the **Cloud SQL Auth Proxy** for all local connections. This allows you to use standard tools (`psql`, DBeaver, Python scripts) by forwarding a local port to the remote instance.

### 1. Prerequisites

-   **Google Cloud SDK** installed and authenticated (`gcloud auth login`).
-   **Cloud SQL Auth Proxy** installed (`brew install cloud-sql-proxy`).
-   **PostgreSQL Client** (`psql`) installed (`brew install libpq` or `brew install postgresql`).

### 2. Start the Proxy

Open a terminal and run the proxy for the target instance.

**For App Dev:**
```bash
cloud-sql-proxy i4g-dev:us-central1:i4g-dev-db
```

**For PII Vault Dev:**
```bash
cloud-sql-proxy i4g-pii-vault-dev:us-central1:i4g-vault-dev-db
```

*Leave this terminal running.*

### 3. Connect via `psql`

In a new terminal, connect using your IAM identity.

```bash
# 1. Get your OAuth access token (used as password)
export PGPASSWORD=$(gcloud auth print-access-token)

# 2. Connect (replace DB_NAME with i4g_db or vault_db)
psql "host=127.0.0.1 port=5432 sslmode=disable user=jerry@intelligenceforgood.org dbname=i4g_db"
```

## User & Permission Management

While Terraform manages the infrastructure (instances, IAM users), **table-level permissions (GRANTS) must be applied manually** inside the database. This is often required after creating new tables via Alembic.

### Key Accounts

| Role | Account Email | Permissions Needed |
| :--- | :--- | :--- |
| **Admins** | `jerry@intelligenceforgood.org`<br>`gcp-i4g-admin@intelligenceforgood.org` | `ALL PRIVILEGES` on tables<br>`CREATE` on schema |
| **Analysts** | `gcp-i4g-analyst@intelligenceforgood.org` | `SELECT` (Read-only) |
| **Service Accounts** | `sa-ingest@i4g-dev.iam`<br>`sa-app@i4g-dev.iam`<br>`sa-vault@i4g-pii-vault-dev.iam` | `SELECT, INSERT, UPDATE, DELETE` |

*Note: Service Account usernames in Postgres are the email **without** `.gserviceaccount.com`.*

### Bootstrapping Permissions (The "Manual" Fix)

If a user or service account gets "Permission Denied", follow these steps to fix it.

#### 1. Connect as Superuser (`postgres`)
You must connect as a user with `GRANT OPTION`. If you don't have the `postgres` password, reset it:

```bash
# Example for PII Vault Dev
gcloud sql users set-password postgres \
    --instance=i4g-vault-dev-db \
    --project=i4g-pii-vault-dev \
    --password=TEMPORARY_PASSWORD
```

Connect via proxy:
```bash
PGPASSWORD=TEMPORARY_PASSWORD psql "host=127.0.0.1 port=5432 sslmode=disable user=postgres dbname=vault_db"
```

#### 2. Grant Permissions
Run the following SQL commands to fix access for all roles.

```sql
-- 1. Grant Usage on Schema
GRANT USAGE ON SCHEMA public TO "jerry@intelligenceforgood.org";
GRANT USAGE ON SCHEMA public TO "gcp-i4g-admin@intelligenceforgood.org";
GRANT USAGE ON SCHEMA public TO "gcp-i4g-analyst@intelligenceforgood.org";
GRANT USAGE ON SCHEMA public TO "sa-ingest@i4g-dev.iam";

-- 2. Grant Admin Access (Developers)
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO "jerry@intelligenceforgood.org";
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO "gcp-i4g-admin@intelligenceforgood.org";

-- 3. Grant Read-Only Access (Analysts)
GRANT SELECT ON ALL TABLES IN SCHEMA public TO "gcp-i4g-analyst@intelligenceforgood.org";

-- 4. Grant App/Ingest Access (Service Accounts)
-- Replace 'sa-ingest' with the relevant SA for the project
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "sa-ingest@i4g-dev.iam";

-- OPTIONAL: Ensure future tables get these grants automatically
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "sa-ingest@i4g-dev.iam";
```

#### 3. Verify Permissions
**Warning:** `information_schema` only shows grants where you are the grantor or grantee. To verify permissions for another user (like `sa-ingest`) when logged in as yourself, use `has_table_privilege`:

```sql
-- Check if sa-ingest can INSERT into pii_tokens
SELECT has_table_privilege('sa-ingest@i4g-dev.iam', 'pii_tokens', 'INSERT');
-- Expected: t (true)
```

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

## Troubleshooting

### "FATAL: database '...' does not exist"
Check the **Overview** table above. You might be connecting to `postgres` instead of `i4g_db` or `vault_db`.

### "FATAL: password authentication failed"
-   **IAM User:** Ensure your OAuth token is fresh (`gcloud auth print-access-token`).
-   **Postgres User:** Ensure you are using the password you just set.

### "Permission denied for table ..."
Follow the **Bootstrapping Permissions** section above to grant the missing privileges.
