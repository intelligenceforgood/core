#!/bin/bash
set -e

# 1. Check for password
if [ -z "$SQL_MIGRATION_PASSWORD" ]; then
    echo "Error: SQL_MIGRATION_PASSWORD is not set."
    echo "Please run: export SQL_MIGRATION_PASSWORD='your_password'"
    exit 1
fi

echo "1. Resetting Azure SQL User..."
python scripts/migration/reset_sql_user.py "$SQL_MIGRATION_PASSWORD"

echo "2. Configuring Environment..."
source scripts/migration/env_template.sh

echo "3. Running Migration..."
# Use -- to pass arguments to the underlying script
i4g azure azure-sql-to-firestore -- --firestore-project i4g-dev
