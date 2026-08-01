# Core — Repo Context

> **For the Antigravity Agent:** Auto-read this file when working in the `core/` repo. For platform-wide architecture and cross-repo routing, read `antigravity/knowledge/architecture/architecture.md`.

## Environment

- **Conda env:** `core`
- **Language:** Python 3.13+ (FastAPI, Pydantic v2, SQLAlchemy)
- **All commands prefix:** `conda run -n core ...`

## Build & Test

```bash
pip install -e .                          # install editable
uvicorn i4g.api.app:app --reload          # dev server
pytest tests/unit                         # unit tests (targeted: pytest tests/unit/<path>)
i4g bootstrap local reset --report-dir data/reports/bootstrap_local  # regenerate sandbox
```

Use `--skip-*` flags on bootstrap for partial rebuilds. Call out if tests are skipped and why.

## Architecture

- **API:** `src/i4g/api/app.py` — FastAPI + rate-limit/TASK_STATUS middleware + report generation lock
- **Review orchestration:** `src/i4g/api/review.py` — search + queue, `ReviewStore`, `HybridRetriever`, audit via `store.log_action`
- **Background jobs:** `src/i4g/worker/jobs/*` and `src/i4g/worker/tasks.py` (e.g., `generate_report_for_case`)
- **Settings:** `i4g.settings.get_settings()` — nested sections via `I4G_*` env vars (double underscores for nesting); never hard-code paths
- **Store builders:** `src/i4g/services/factories.py` — use for structured/review/vector/intake/evidence stores

## Environment Profiles

- `I4G_ENV=local` — mock identity + SQLite/Chroma
- `I4G_ENV=i4g-dev` / `i4g-prod` — PostgreSQL (Cloud SQL), Secret Manager, Artifact Registry, Cloud Run
- `Settings._resolve_paths` normalizes relative paths — pass project-relative references, not manual `Path` math

## Data & Secrets

- Runtime artifacts in `data/` (SQLite, Chroma, OCR outputs, reports) — refresh via bootstrap, not custom helpers
- Non-`NEXT_PUBLIC_*` secrets in `.env.local` or platform secret managers
- See `docs/design/storage.md` for data flow and retention policies

## Docker Build

```bash
scripts/build_image.sh [core-svc|dossier-job|ingest-job|intake-job|report-job] dev
```

Requires `gcloud` auth. UI image: `cd ui/ && scripts/build_image.sh i4g-console dev`.

## Pre-Commit

```bash
conda run -n core pre-commit run --all-files   # Pass 1 — auto-fixes formatting
git add -u
conda run -n core pre-commit run --all-files   # Pass 2 — must exit clean
```

## Coding Conventions

- Python: full type hints, Google-style docstrings, Black/isort at 120-char lines
- Pydantic: `snake_case` internally, `alias_generator = to_camel` for JSON — never write manual translation functions
- For complete language and project standards, read `antigravity/knowledge/standards/python.md`

## External Integrations

- UI analyst console calls: `/reviews/search`, `/reviews/search/history`, saved-search CRUD, `/reviews/{id}`, `/tasks/{task_id}` — keep payloads + audit logging in sync
- Report generation: `i4g/reports` templates + worker tasks; TASK_STATUS emits progress until Redis replaces in-memory map
- Ingestion: route through `i4g.ingestion` + `worker/jobs` so CLI and API paths stay aligned

## Env + Smoke Discipline

When adding/changing settings or job envs: (a) add coverage under `tests/unit/settings/`, (b) refresh `docs/config/` env-var table + YAML manifest, (c) run local smoke (`conda run -n core I4G_PROJECT_ROOT=$PWD I4G_ENV=dev I4G_LLM__PROVIDER=mock i4g jobs ingest ...`) before any Cloud Run job.
