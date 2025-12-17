# Runbooks (Operations)

Use these when you need to act quickly in production or lower environments.

## Available runbooks
- Analyst console triage: [analyst_runbook.md](analyst_runbook.md)
- Console operations: [console/search.md](console/search.md), [console/reports.md](console/reports.md), [console/dossier_monitoring.md](console/dossier_monitoring.md)
- Dossier handoff: [dossiers_subpoena_handoff.md](dossiers_subpoena_handoff.md)
- Dossier deploy checklist: [dossiers_deployment_checklist.md](dossiers_deployment_checklist.md)
- Hybrid search deployment checklist: [hybrid_search_deployment_checklist.md](hybrid_search_deployment_checklist.md)

> Tip: If you landed here from an old link to `docs/analyst_runbook.md`, this is the new index.

## How to use
- Each runbook should start with symptoms, impact, checkpoints, and rollback/exit criteria.
- Keep commands copy-pasteable and prefer documented Make targets or scripts.
- Use runbooks for incident response and live ops; if you need a longer setup or learning path, link to a cookbook.
