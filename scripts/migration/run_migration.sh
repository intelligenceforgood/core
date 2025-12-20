#!/bin/bash
set -e

echo "Running Azure SQL -> Firestore Migration..."
echo "Using Azure AD Authentication (requires 'az login')"

# Ensure we have the environment variables (connection string base)
source scripts/migration/env_template.sh

# Run the migration using AAD
# Note: We use -- to pass arguments to the underlying script
i4g azure azure-sql-to-firestore -- --firestore-project i4g-dev --use-aad

echo "✅ Migration Complete!"
