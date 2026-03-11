# Cloud SQL Primer

This guide explains how to inspect, query, and manage permissions for the Cloud SQL (PostgreSQL) databases used by the i4g platform.

## Overview

The platform uses two distinct Cloud SQL instances per environment:

| Project       | Environment | Instance Name       | Database Name | Description                                      |
| :------------ | :---------- | :------------------ | :------------ | :----------------------------------------------- |
| **App**       | `dev`       | `i4g-dev-db`        | `i4g_db`      | Main application database (cases, reviews, etc.) |
| **App**       | `prod`      | `i4g-prod-db`       | `i4g_db`      | Production application database                  |
| **PII Vault** | `dev`       | `i4g-vault-dev-db`  | `vault_db`    | Isolated PII storage (tokens, secrets)           |
| **PII Vault** | `prod`      | `i4g-vault-prod-db` | `vault_db`    | Production PII storage                           |

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

## 2. `i4g db` CLI (Recommended)

The `i4g db` CLI automates proxy lifecycle, Alembic migrations, and permission
grants. It reads passwords from `config/settings.local.toml` under `[db_admin]`,
so you only configure credentials once.

### Prerequisites

1. Install `cloud-sql-proxy` (must be on `$PATH`).
2. Add passwords to `config/settings.local.toml`:

   ```toml
   [db_admin]
   dev_password = "..."
   prod_password = "..."
   dev_vault_password = "..."
   prod_vault_password = "..."
   ```

   Alternatively, set env vars: `I4G_DB_ADMIN__DEV_PASSWORD`, etc.

### Running Migrations

```bash
# Dev main DB
i4g db migrate dev

# Dev vault DB
i4g db migrate dev --vault

# Prod main DB
i4g db migrate prod

# Prod vault DB
i4g db migrate prod --vault

# Preview without executing
i4g db migrate dev --dry-run
```

Each command starts cloud-sql-proxy, runs `alembic upgrade head` with the
correct config (`alembic.ini` for app, `alembic_vault.ini` for vault), and
stops the proxy automatically.

### Granting Permissions

```bash
# Dev main DB — grants to all SAs + admin users
i4g db grant-permissions dev

# Dev vault DB
i4g db grant-permissions dev --vault

# Preview the SQL without executing
i4g db grant-permissions prod --dry-run
```

This grants `USAGE`, `ALL PRIVILEGES` on existing tables/sequences, and sets
`ALTER DEFAULT PRIVILEGES` so future Alembic-created objects are automatically
accessible. Principals that don't exist on the target instance are skipped
with a warning.

### Checking Migration Status

```bash
# Show current Alembic revision
i4g db status dev
i4g db status prod --vault
```

### Port Assignments

The CLI uses fixed ports per environment to avoid conflicts when multiple
proxies are running:

| Target     | Port |
| ---------- | ---- |
| dev app    | 5432 |
| dev vault  | 5433 |
| prod app   | 5434 |
| prod vault | 5435 |

> **Tip:** For quick ad-hoc SQL queries, use `gcloud beta sql connect` (section
> 1 Method B) instead. The CLI is designed for automated schema management, not
> interactive sessions.

---

## 3. Schema Management (Re-initializing the DB)

If you need to reset the environment to a "virgin" state (e.g., during a full
bootstrap reset), follow these manual steps. For routine migrations, use
`i4g db migrate` (section 2) instead.

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
ALEMBIC_DATABASE_URL="postgresql+psycopg2://postgres:YOUR_PASSWORD@127.0.0.1:5432/i4g_db" \
  conda run -n i4g alembic -c alembic.ini upgrade head

# 2. Migrate Vault DB (Port 5433)
ALEMBIC_DATABASE_URL="postgresql+psycopg2://postgres:YOUR_PASSWORD@127.0.0.1:5433/vault_db" \
  conda run -n i4g alembic -c alembic_vault.ini upgrade head
```

> **Important:**
>
> - Use `postgresql+psycopg2://` (not bare `postgresql://`) to ensure the
>   correct driver is loaded.
> - Always run via `conda run -n i4g` — Alembic's `env.py` imports
>   `i4g.settings` and `i4g.store.sql`, so the package must be importable.
> - Replace `YOUR_PASSWORD` with the actual `postgres` user password.

### First-time vault migration: setting the postgres password

When the vault instance is first provisioned via Terraform, only an IAM-based
admin user exists — the built-in `postgres` user has no password set, which
blocks Alembic. Follow these steps before running the migration for the first
time.

1. **Set a temporary password** for the `postgres` user:

   ```bash
   gcloud sql users set-password postgres \
       --instance=i4g-vault-dev-db \
       --project=i4g-pii-vault-dev \
       --password=<YOUR_TEMP_PASSWORD>
   ```

2. **Switch gcloud context** to the vault project (the proxy picks it up
   automatically, but explicit is safer):

   ```bash
   gcloud config set project i4g-pii-vault-dev
   ```

3. **Start the proxy** for the vault instance on port 5433 (or any free port):

   ```bash
   cloud-sql-proxy i4g-pii-vault-dev:us-central1:i4g-vault-dev-db?port=5433
   ```

4. **Run the Alembic migration** in a separate terminal:

   ```bash
   ALEMBIC_DATABASE_URL="postgresql+psycopg2://postgres:<YOUR_TEMP_PASSWORD>@127.0.0.1:5433/vault_db" \
     conda run -n i4g alembic -c alembic_vault.ini upgrade head
   ```

5. **Verify** via psql:

   ```bash
   psql "host=127.0.0.1 port=5433 sslmode=disable user=postgres dbname=vault_db"
   # \dt  — should list pii_tokens and alembic_version
   ```

6. **Restore gcloud context** after you are done:

   ```bash
   gcloud config set project i4g-dev
   ```

---

## 4. Permission Management (Manual)

After re-initializing the schema, you must ensure that the application service
accounts have the correct permissions. **Prefer `i4g db grant-permissions`
(section 2)** — it runs all the statements below automatically.

### Key Accounts

| Role                 | Account Email                                                                                                  | Permissions Needed                               |
| :------------------- | :------------------------------------------------------------------------------------------------------------- | :----------------------------------------------- |
| **Admins**           | `jerry@intelligenceforgood.org`<br>`gcp-i4g-admin@intelligenceforgood.org`                                     | `ALL PRIVILEGES` on tables<br>`CREATE` on schema |
| **Service Accounts** | `sa-ingest@i4g-dev.iam`<br>`sa-app@i4g-dev.iam`<br>`sa-vault@i4g-pii-vault-dev.iam`<br>`sa-report@i4g-dev.iam` | `SELECT, INSERT, UPDATE, DELETE`                 |

### Granting Permissions

Run these commands as the `postgres` user (via `psql` or `gcloud sql connect`).

> **Critical:** You must grant privileges on **both tables and sequences**,
> and set **default privileges** so that future tables created by `postgres`
> (e.g. via Alembic migrations) are automatically accessible. Without
> `ALTER DEFAULT PRIVILEGES`, new tables require re-running the grants.

**Main DB (`i4g_db`):**

```sql
\c i4g_db

-- Grant Usage on Schema
GRANT USAGE ON SCHEMA public TO "sa-ingest@i4g-dev.iam";
GRANT USAGE ON SCHEMA public TO "sa-app@i4g-dev.iam";
GRANT USAGE ON SCHEMA public TO "sa-report@i4g-dev.iam";

-- Grant Table Access (existing tables)
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO "sa-ingest@i4g-dev.iam";
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO "sa-app@i4g-dev.iam";
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO "sa-report@i4g-dev.iam";

-- Grant Sequence Access (for auto-increment IDs)
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO "sa-ingest@i4g-dev.iam";
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO "sa-app@i4g-dev.iam";
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO "sa-report@i4g-dev.iam";

-- Default privileges for future tables/sequences created by postgres
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO "sa-ingest@i4g-dev.iam";
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO "sa-app@i4g-dev.iam";
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO "sa-report@i4g-dev.iam";
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO "sa-ingest@i4g-dev.iam";
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO "sa-app@i4g-dev.iam";
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO "sa-report@i4g-dev.iam";
```

**IAM User Access (for Cloud SQL Studio and psql via IAM):**

```sql
-- Grant an IAM user full access (tables, sequences, and defaults)
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO "jerry@intelligenceforgood.org";
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO "jerry@intelligenceforgood.org";
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO "jerry@intelligenceforgood.org";
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO "jerry@intelligenceforgood.org";
```

> **Common mistake:** granting only sequence privileges won't let you query
> tables. You need `GRANT ... ON ALL TABLES` for SELECT/INSERT/UPDATE/DELETE.

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

## 5. Common Queries

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

## 6. Alembic Migration Workflow (Manual)

### Checking Migration Status

For quick checks use `i4g db status <env>` (section 2). For manual inspection:

```bash
ALEMBIC_DATABASE_URL="postgresql+psycopg2://postgres:YOUR_PASSWORD@127.0.0.1:5432/i4g_db" \
  conda run -n i4g alembic -c alembic.ini current
```

To see the full migration history:

```bash
conda run -n i4g alembic -c alembic.ini history
```

### Writing Migrations

All schema changes **must** go through Alembic migrations. Do not rely on
`metadata.create_all()` — it works locally with SQLite but does nothing on
Cloud SQL.

Migrations live in `src/i4g/migrations/versions/`. Follow the naming
convention: `YYYYMMDD_NN_description.py`.

When a migration adds tables or columns that may already exist (e.g. because
`create_all()` ran locally), use `inspect()` guards:

```python
from sqlalchemy import inspect

def upgrade() -> None:
    conn = op.get_bind()
    insp = inspect(conn)
    existing_tables = insp.get_table_names()

    if "my_table" not in existing_tables:
        op.create_table("my_table", ...)

    existing_columns = {c["name"] for c in insp.get_columns("cases")}
    if "my_column" not in existing_columns:
        op.add_column("cases", sa.Column("my_column", ...))
```

### Fixing a "Stamp Without Schema" Problem

If `alembic current` shows the latest revision but the tables don't actually
exist (e.g. someone ran `alembic stamp` without running the migration), fix
it by downgrading and re-upgrading:

```bash
# Step back to the revision before the missing tables
ALEMBIC_DATABASE_URL="..." \
  conda run -n i4g alembic -c alembic.ini downgrade PREVIOUS_REVISION

# Re-run forward
ALEMBIC_DATABASE_URL="..." \
  conda run -n i4g alembic -c alembic.ini upgrade head
```

If the downgrade also fails (trying to drop objects that don't exist), apply
the SQL directly and leave Alembic's stamp in place:

```sql
-- Example: manually create a missing table
CREATE TABLE IF NOT EXISTS accounts (
    email TEXT PRIMARY KEY,
    role TEXT NOT NULL DEFAULT 'analyst',
    display_name TEXT,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_accounts_role ON accounts (role);

-- Example: manually add missing columns
ALTER TABLE cases ADD COLUMN IF NOT EXISTS risk_score NUMERIC(5,1) NOT NULL DEFAULT 0;
ALTER TABLE cases ADD COLUMN IF NOT EXISTS taxonomy_version TEXT;
CREATE INDEX IF NOT EXISTS idx_cases_risk_score ON cases (risk_score);
```

### Seeding Initial Data

After creating tables, seed required records:

```sql
-- Create an admin account
INSERT INTO accounts (email, role, display_name, is_active)
VALUES ('jerry@intelligenceforgood.org', 'admin', 'Jerry', true);
```

---

## 7. Troubleshooting

### "FATAL: database '...' does not exist"

Check the **Overview** table above. You might be connecting to `postgres` instead of `i4g_db` or `vault_db`.

### "FATAL: password authentication failed"

- **IAM User:** Ensure your OAuth token is fresh (`gcloud auth print-access-token`).
- **Postgres User:** Ensure you are using the password you just set.

### "Permission denied for table ..."

Follow the **Permission Management** section above to grant the missing privileges. Remember that granting permissions on **sequences only** does not grant table access — you need separate `GRANT ... ON ALL TABLES` and `GRANT ... ON ALL SEQUENCES` statements.

### Alembic "upgrade head" does nothing

Run `alembic current` to check the stamped revision. If it already shows
`(head)`, the database thinks the migration already ran. See the
**Fixing a "Stamp Without Schema" Problem** section above.

### Alembic "table already exists" / "column already exists"

This happens when `create_all()` created objects outside of Alembic (common
with local SQLite). Migration scripts should use `inspect()` guards to
check for existing objects before creating them. See **Writing Migrations**
above.

### Alembic command fails with ImportError

Always run Alembic via `conda run -n i4g alembic ...` — the `env.py` file
imports `i4g.settings` and `i4g.store.sql`, which require the conda
environment with the i4g package installed.

### "Driver not found" or wrong connection

Use `postgresql+psycopg2://` as the URL scheme, not bare `postgresql://`.
The psycopg2 driver must be installed in the conda environment.
