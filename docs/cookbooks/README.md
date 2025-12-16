# Cookbooks (How-Tos)

Use these step-by-step guides to create artifacts, run smokes, or set up infrastructure.

## Available recipes
- Local smoke / health checks: [smoke_test.md](smoke_test.md)
- Bootstrap or refresh sandbox/dev data: [bootstrap_environments.md](bootstrap_environments.md)
- Run retrieval pipeline on GCP: [../retrieval_gcp_guide.md](../retrieval_gcp_guide.md)
- Generate settings manifests and config tables: [../config/README.md](../config/README.md)
- Deploy hybrid search checklist: [../hybrid_search_deployment_checklist.md](../hybrid_search_deployment_checklist.md)

## Add a new recipe
- Keep it task-focused with inputs/outputs and estimated time.
- Link any scripts or Make targets; prefer reproducible commands over one-off env var lists.
- Cross-link to runbooks when the recipe is also used during incidents; cookbooks are for repeatable setup/change work, runbooks are for on-call response.
