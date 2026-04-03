# Cookbooks (How-Tos)

Use these step-by-step guides to create artifacts, run smokes, or set up infrastructure.

## Available recipes

- Local smoke / health checks: [smoke_test.md](smoke_test.md)
- Bootstrap or refresh sandbox/dev data: [bootstrap_environments.md](bootstrap_environments.md)
- Configure Google Workspace SMTP for notifications: [google_workspace_smtp_setup.md](google_workspace_smtp_setup.md)
- Prepare bootstrap data bundles (GCS upload): [prepare_bootstrap_bundles.md](prepare_bootstrap_bundles.md)
- Cloud SQL inspection, querying, and permissions: [cloud_sql_primer.md](cloud_sql_primer.md)
- Configure GitHub Actions CI/CD with Workload Identity Federation: [github_actions_setup.md](github_actions_setup.md)
- Run retrieval pipeline on GCP: [../development/retrieval_gcp_guide.md](../development/retrieval_gcp_guide.md)
- Generate settings manifests and config tables: [../config/README.md](../config/README.md)
- Deploy hybrid search checklist: [../runbooks/hybrid_search_deployment_checklist.md](../runbooks/hybrid_search_deployment_checklist.md)

## Add a new recipe

- Keep it task-focused with inputs/outputs and estimated time.
- Link any scripts or Make targets; prefer reproducible commands over one-off env var lists.
- Cross-link to runbooks when the recipe is also used during incidents; cookbooks are for repeatable setup/change work, runbooks are for on-call response.
