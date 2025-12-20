#!/bin/bash
# Source this file to set up your environment for Azure migration
# Usage: source scripts/migration/env_template.sh

# 1. Set your password here (do not commit this file with the real password!)
export SQL_MIGRATION_PASSWORD="YOUR_PASSWORD_HERE"

# 2. The connection string uses the password variable
# Note: LoginTimeout=30 is added to fail fast if firewall rules are missing
export AZURE_SQL_CONNECTION_STRING="Driver={ODBC Driver 18 for SQL Server};Server=tcp:intelforgood.database.windows.net,1433;Database=intelforgood;Uid=migration_user;Pwd=${SQL_MIGRATION_PASSWORD};Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=30;"

# 3. Other Azure variables if needed
# export AZURE_STORAGE_CONNECTION_STRING="..."
# export AZURE_SEARCH_ADMIN_KEY="..."

echo "Environment variables set for Azure migration."
echo "Verify with: echo \$AZURE_SQL_CONNECTION_STRING"
