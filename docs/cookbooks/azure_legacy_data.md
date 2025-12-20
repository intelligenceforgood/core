# Azure Legacy Data Workflow

This cookbook captures the Azure-specific environment variables, credentials, and commands that the migration scripts expect when rebuilding the legacy export bundle. Treat it as your quickstart while you work through the Azure resources.

## Environment variables
Set these before running any `conda run -n i4g i4g azure ...` command so every migration helper can pick up credentials without prompting.

- `AZURE_SQL_CONNECTION_STRING` – ODBC string for the `intelforgood` server. Contains driver, server, database, `migration_user`, and `Pwd=${SQL_MIGRATION_PASSWORD}`.
- `SQL_MIGRATION_PASSWORD` – Password used by `migration_user`; the connection string substitutes this value. Keep it out of logs.
- `AZURE_STORAGE_CONNECTION_STRING` – Storage account `attachmentsdata` connection string. Used by `azure-blob-to-gcs`.
- `AZURE_SEARCH_ENDPOINT` – Endpoint for the `ifg-ai-search` Cognitive Search service.
- `AZURE_SEARCH_ADMIN_KEY` – Admin key for exporting indexes.
- `AZURE_SEARCH_ADMIN_KEY` (yes, duplicated) intentionally overlaps with the search sync; keep it current.
- `RUN_DATE` – Optional, used when naming exported artifacts (e.g., `20251217`).
- `SQLCMDPASSWORD` – Helper for CLI utilities such as `sqlcmd`; keep it aligned with `SQL_MIGRATION_PASSWORD`.

Store these securely (Secret Manager, key vault) and load them before running migration scripts. The weekly refresh orchestrator already reads from `AZURE_SQL_CONNECTION_STRING` and the storage/search secrets.

## Helpful Azure CLI recipes
Run all commands from the `intelforgood` resource group unless noted.

### Sign in and pick the subscription
```bash
az login --tenant 40d408e0-0cf0-4eeb-9c34-e9114b0814a3
az account set --subscription "Intelligence for Good Sub"
```

### Read secrets stored in Key Vault (if you prefer Vault over env vars)
```bash
az keyvault secret show \
  --vault-name ifg-apikeys \
  --name AZURE-STORAGE-CONNECTION-STRING \
  --query value -o tsv
```

### Manage SQL firewall rules
Allow your current public IP:
```bash
az sql server firewall-rule create \
  --name allow-export-<YYYYMMDD> \
  --server intelforgood \
  --resource-group intelforgood \
  --start-ip-address <your-ip> \
  --end-ip-address <your-ip>
```
Remove it when you are done:
```bash
az sql server firewall-rule delete \
  --name allow-export-<YYYYMMDD> \
  --server intelforgood \
  --resource-group intelforgood
```

### Inspect search + storage resources
Use these commands to validate the Azure services that feed the legacy export.

```bash
for account in attachmentsdata intelforgood9877 intelforgooda41c processgroupsio processintakeform3; do
  az storage container list \
    --account-name "$account" \
    --auth-mode login \
    --output table
done
```
- Run the loop to enumerate the containers inside every storage account we currently touch. Today the only populated containers that matter for the legacy export are `intake-form-attachments` (forms) and `groupsio-attachments` (discussion blobs); the `attachmentsdata`/`reports` buckets you saw before are historical artifacts and no longer backed by data. Mirror the two canonical containers to GCS and downstream storage, just as the legacy tooling in [dtp/IFG-AzureFunctions/utilities/groupsio_transfer/att_transfer.py](dtp/IFG-AzureFunctions/utilities/groupsio_transfer/att_transfer.py#L9-L40) and [dtp/IFG-AzureFunctions/process_intake_forms/config.py](dtp/IFG-AzureFunctions/process_intake_forms/config.py#L1-L25) expect. Confirm the names you plan to pass to `i4g azure azure-blob-to-gcs` are listed by repeatedly running this loop, since passing a non-existent container now triggers the `ContainerNotFound` error you saw.

```bash
az resource show \
  --resource-type Microsoft.Search/searchServices \
  --name ifg-ai-search \
  --resource-group intelforgood \
  --output jsonc
```
- Returns metadata for the Cognitive Search instance that backs the `ifg-ai-search` indexes; confirm the service is healthy and note properties such as replicas or SKUs.

```bash
az rest --method post \
  --url "https://management.azure.com/subscriptions/$SUBSCRIPTION_ID/resourceGroups/intelforgood/providers/Microsoft.Search/searchServices/ifg-ai-search/listAdminKeys?api-version=2023-11-01"
```
- Hits the management API to fetch the current admin keys for the search service when you don’t want to store them locally. Combine with `jq` or store the result in an env var before running search export.

## References from the migration flow
1. `AZURE_SQL_CONNECTION_STRING` is consumed by `azure_sql_to_firestore`.
2. Storage/search vars feed `azure-blob-to-gcs` and `azure-search-export` / `azure-search-to-vertex`.
3. `SQLCMDPASSWORD` is useful when you need to run `sqlcmd` interactively for troubleshooting (the script doesn’t use it directly).

Keep this document near `docs/cookbooks/bootstrap_environments.md` so the next time you rebuild the legacy bundle you can refresh your muscle memory without digging through notes.
