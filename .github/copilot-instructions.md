# Copilot Instructions for i4g/core

**Unified Workspace Context:** This repository is part of the `i4g` multi-root workspace. The `core/` repository acts as the primary entry point for coding conventions and architectural standards. These instructions are synchronized to ensure consistent behavior across all roots.

1. **Rehydrate & Daily Loop** – Start every session by checking `git status -sb`. Skim `planning/change_log.md` for recent decisions. Check `.entire/` and `.claud/` folders (if present) for conversation context from prior commits — these are managed by the Entire tool and capture AI session history per commit.
   - **Plan:** Check active work stream in `planning/tasks/quality_elevation_plan.md`.
   - **Build:** Run `uvicorn i4g.api.app:app --reload` for API; use `conda run -n i4g ...`.
   - **Test:** Run `pytest tests/unit` or targeted smokes. If skipping, record why.
   - **Docs:** Update `docs/` and `planning/change_log.md` when behavior/env vars change.
   - **Wrap-up:** Update `planning/change_log.md` with any significant progress.

2. **Config Discipline** – Always fetch settings via `i4g.settings.get_settings()`; nested sections (`api`, `storage`, `vector`, `llm`, `identity`, etc.) are mutated by `_apply_environment_overrides`, so override via env vars (`I4G_*`, double underscores) rather than hard-coded paths. Store builders live in `src/i4g/services/factories.py`; use them for structured/review/vector/intake/evidence stores.

3. **Coding Conventions** – Follow `core/.github/general-coding.instructions.md` for all language-specific standards (Python, TypeScript, Terraform, SQL, Shell, HTML/CSS, config files). Use each language's idiomatic conventions — do not invent project-specific patterns. Key highlights for this repo: Python uses full type hints, Google-style docstrings, Black/isort at 120-char lines. Pydantic models use `snake_case` internally with `alias_generator = to_camel` for JSON output. Never write manual camelCase/snake_case translation functions.

4. **Core Architecture** – `src/i4g/api/app.py` wires FastAPI routers, middleware (rate limit + TASK_STATUS), and the report-generation lock. `src/i4g/api/review.py` orchestrates search + queue actions backed by `ReviewStore`, `HybridRetriever`, and audit logging via `store.log_action`. Background work executes through `src/i4g/worker/jobs/*` and `src/i4g/worker/tasks.py` (e.g., `generate_report_for_case`).

5. **Developer Loop** – Install editable (`pip install -e .`) so CLI entry points (`i4g`) resolve. Typical cycle: `uvicorn i4g.api.app:app --reload`, `pytest tests/unit`, and targeted demos in `tests/adhoc/` for OCR/extraction/report validation. Regenerate the sandbox with `i4g bootstrap local reset --report-dir data/reports/bootstrap_local` (use `--skip-*` flags for partial rebuilds). Call out if tests were skipped.

6. **Environment Profiles** – `I4G_ENV=local` enforces mock identity + SQLite/Chroma; cloud targets (`i4g-dev`, `i4g-prod`) expect PostgreSQL, Secret Manager, Artifact Registry, and Cloud Run. `Settings._resolve_paths` normalizes relative paths—pass project-relative references instead of manual `Path` math.

7. **Data & Secrets** – Runtime artifacts live in `data/` (SQLite DB, Chroma store, OCR outputs, reports). Delete/refresh them via the bootstrap script rather than custom helpers. Store non-`NEXT_PUBLIC_*` secrets in `.env.local` or platform secret managers. Refer to `docs/design/storage.md` for data flow and retention policies in both local and dev environments.

8. **Docker Build Reference** – Use `scripts/build_image.sh` (requires `gcloud` auth).
   - UI: `cd ui/ && scripts/build_image.sh i4g-console dev`
   - Core: `scripts/build_image.sh [fastapi|dossier-job|ingest-job|intake-job|report-job|account-job] dev`

9. **External Integrations** – The Next.js analyst console calls `/reviews/search`, `/reviews/search/history`, saved-search CRUD endpoints, `/reviews/{id}`, and `/tasks/{task_id}`; keep payloads + audit logging in sync. Report generation uses `i4g/reports` templates plus worker tasks; ensure TASK_STATUS emits progress until Redis replaces the in-memory map. Ingestion enhancements must route through `i4g.ingestion` + `worker/jobs` so CLI and API paths stay aligned.

10. **Repository Roles & Instruction Placement** – This workspace is multi-root. Keep per-repo instruction files in each repo’s `.github/` directory.
    - `core/` — Primary Python + docs repo. Source of truth for shared conventions.
    - `ui/` — Node.js/Next.js UI repo.
    - `planning/`, `docs/`, `infra/`, `mobile/`, `dtp/`, `arch-viz/` — Specialized components following `core` standards where applicable.

11. **Docs: code snippets policy** – Do NOT paste entire source files into markdown pages. Instead:
    - Include a short, focused snippet (only the lines relevant to the doc).
    - Add a repository link pointing to the full file path (e.g., `ui/docker/ui-console.Dockerfile`).
    - For large files, include a one-paragraph summary and an inline link to the file rather than embedding the whole file content.

12. **Infrastructure Alignment** – Terraform lives in the sibling `infra/` repo (Workload Identity Federation via `modules/iam/workload_identity_github`). Target `i4g-dev` before `i4g-prod`, impersonate `sa-infra` with `gcloud auth application-default login`, and ensure Cloud Run commands in docs (e.g., `docs/design/architecture.md`) match reality.

13. **Merge Readiness & Pre-Merge Review** – When the user requests a **pre-merge review**, execute the full checklist in `core/.github/pre-merge-review.instructions.md`. This includes: (a) coding standards audit against `core/.github/general-coding.instructions.md` — type hints on every function, Google-style docstrings on all public/private methods, no unused imports or dead code; (b) code quality — safe variable scoping, specific exception handling, no hard-coded secrets; (c) architecture alignment — correct use of stores/factories/settings; (d) test suite passes with zero failures; (e) docs/config updated if behavior changed. Produce a summary of issues found, fixes applied, test results, and remaining items.

14. **Env + Smoke Discipline** – Treat environment variables as a contract. When adding or changing settings/job envs: (a) add or update coverage under `tests/unit/settings/` so overrides and defaults are validated locally, (b) refresh the env-var reference in `docs/config/` (table plus YAML manifest) so docs stay in sync, and (c) execute the local sandbox smoke (`conda run -n i4g I4G_PROJECT_ROOT=$PWD I4G_ENV=dev I4G_LLM__PROVIDER=mock i4g jobs account ...`) before any Cloud Run job. No cloud smoke runs should happen until the local run succeeds with the same env overrides.

15. **UI Build Procedure** – To build the UI image, always change directory to the UI root first (`cd ui/`) and run the build script from there: `scripts/build_image.sh i4g-console dev`. Do not attempt to build from the workspace root.

16. **Entire Tool Integration** – The Entire tool tracks AI conversation context per commit in `.entire/` and `.claud/` folders. These folders are present in each repo root. `settings.json` is committed (shared config); `logs/`, `metadata/`, and `tmp/` are gitignored (local). Do NOT modify, delete, or overwrite files in `.entire/` or `.claud/` — they are managed exclusively by the Entire tool. During rehydration, read any available context from these folders to understand recent session history.
