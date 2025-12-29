# PII Vault Database Migration Guide

This guide details how to connect to the private PII Vault Cloud SQL instance from your local machine to run schema migrations.

## Prerequisites

- **GCP Project:** `i4g-pii-vault-dev`
- **Instance:** `i4g-vault-dev-db`
- **Region:** `us-central1`
- **Tool:** `cloud-sql-proxy` (Found at `/opt/homebrew/bin/cloud-sql-proxy`)

## Step 1: Authenticate & Switch Context

Ensure you are logged in and targeting the correct project.

```bash
# 1. Login to gcloud (if not already)
gcloud auth login

# 2. Set the project context to the vault project
gcloud config set project i4g-pii-vault-dev

# 3. Verify you are pointing to the right place
gcloud config get-value project
# Output should be: i4g-pii-vault-dev
```

## Step 2: Configure Database User

Since we provisioned the database via Terraform without hardcoding passwords, we need to set a password for the `postgres` admin user to run the initial migration.

```bash
# Set a temporary password for the 'postgres' user
# Replace <YOUR_TEMP_PASSWORD> with a strong password
gcloud sql users set-password postgres \
    --instance=i4g-vault-dev-db \
    --password=<YOUR_TEMP_PASSWORD>
```

*Note: In the future, we can add your IAM identity as a database user for passwordless access, but using the `postgres` user is the standard way for initial schema setup.*

## Step 3: Start Cloud SQL Auth Proxy

The proxy creates a secure tunnel from your local machine (`localhost`) to the Cloud SQL instance.

Open a **new terminal tab** and run:

```bash
# Start the proxy on port 5432
cloud-sql-proxy i4g-pii-vault-dev:us-central1:i4g-vault-dev-db
```

*Keep this terminal running. You should see "Ready for new connections".*

## Step 4: Run Alembic Migration

Switch back to your **original terminal** (where you are in the `i4g/core` directory).

1.  **Export Environment Variables**: Configure the app to talk to the local proxy.

```bash
# Explicit connection string for Alembic
# We use 'postgresql+pg8000' as it is the driver included in our environment.
# Replace <YOUR_TEMP_PASSWORD> with the password you set in Step 2.
export ALEMBIC_DATABASE_URL="postgresql+pg8000://postgres:<YOUR_TEMP_PASSWORD>@127.0.0.1:5432/postgres"
```

2.  **Run the Migration**:

```bash
# Ensure you are in the core directory
cd core

# Apply the schema using the vault-specific configuration
alembic -c alembic_vault.ini upgrade head
```

## Step 5: Verification

You can verify the table exists using `psql` or by checking the logs.

```bash
# Optional: Connect with psql to verify
psql "host=127.0.0.1 port=5432 sslmode=disable user=postgres dbname=postgres"
# Password: <YOUR_TEMP_PASSWORD>
# \dt
# You should see 'pii_tokens' and 'alembic_version' tables.
```

## Cleanup

1.  Stop the proxy (Ctrl+C).
2.  (Optional) Switch your gcloud config back to your main dev project if needed:
    ```bash
    gcloud config set project i4g-dev
    ```
