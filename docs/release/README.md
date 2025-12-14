# Release and Migration

Launch pad for shipping changes and handling upgrades.

## Current guides
- Hybrid search deployment checklist: [../hybrid_search_deployment_checklist.md](../hybrid_search_deployment_checklist.md)
- IAM and access alignment: [../iam.md](../iam.md)

## Standard release checklist
- Verify tests: `pytest tests/unit` (add targeted suites for affected areas), and run smoke(s) from [../cookbooks/smoke_test.md](../cookbooks/smoke_test.md).
- Update docs: architecture, [../tdd.md](../tdd.md) when contracts change, config manifests, and any impacted runbooks/cookbooks.
- Versioning/tagging: tag mainline builds and note breaking changes in `planning/change_log.md`.
- Rollback plan: identify revert PR or deploy artifact, and ensure data migrations have down/restore steps.

## Migration guidance
- Data/DB: document forward and backward compatibility, provide migration scripts, and include back-out steps.
- Settings/env: add env overrides to `tests/unit/settings/`, regenerate manifests, and update [../config/README.md](../config/README.md).
- Secrets/keys: capture rotation steps and WIF/IAM prerequisites; prefer Secret Manager over inline envs.
