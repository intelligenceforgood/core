# i4g/core

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![Docs](https://img.shields.io/badge/Docs-Docs%20Hub-green.svg)](docs/README.md)
[![Tests](https://img.shields.io/badge/Tests-pytest-lightgrey.svg)](tests/README.md)

Backend services, jobs, and documentation for the Intelligence for Good platform. This repo holds the FastAPI API, worker jobs, reports, settings, and the canonical docs. The Next.js portal lives in `ui/`, infra code in `infra/`, and planning artifacts in `planning/`.

## What this repo contains
- FastAPI backend and routers: `src/i4g/api/`
- Worker jobs and tasks: `src/i4g/worker/`
- Stores, retrieval, tokenization: `src/i4g/store/`, `src/i4g/services/`, `src/i4g/pii/`
- Settings and manifests: `config/settings.*.toml`
- Docs hub and design docs: `docs/`
- Reports/templates and scripts: `reports/`, `scripts/`
- Tests: `tests/`

## Quickstart (local)
- Prereqs: Conda env `i4g` (see docs), Python 3.11+, Node if running the UI.
- Install: `pip install -e .`
- Seed local data: `python scripts/bootstrap_local_sandbox.py --reset`
- Run API: `uvicorn i4g.api.app:app --reload`
- Run tests: `pytest tests/unit`
- Settings: use `config/settings.default.toml` plus overrides in `config/settings.local.toml` or env vars (`I4G_*`). Always load via `i4g.settings.get_settings()`.

## Documentation map
- Docs hub and navigation: [docs/README.md](docs/README.md)
- Architecture (diagrams, deployment profiles): [docs/architecture.md](docs/architecture.md)
- Technical design and contracts: [docs/tdd.md](docs/tdd.md)
- Developer workflow: [docs/dev_guide.md](docs/dev_guide.md)
- Cookbooks (how-tos): [docs/cookbooks/README.md](docs/cookbooks/README.md)
- Runbooks (ops): [docs/runbooks/README.md](docs/runbooks/README.md)
- Testing and TDD: [docs/testing/README.md](docs/testing/README.md)
- Release and migration: [docs/release/README.md](docs/release/README.md)
- Config reference: [docs/config/README.md](docs/config/README.md)
- Security and IAM: [docs/iam.md](docs/iam.md), [docs/compliance.md](docs/compliance.md), [docs/confidentiality_agreement.md](docs/confidentiality_agreement.md)
- Planning workspace (separate repo folder): [planning/README.md](../planning/README.md)

## Common entrypoints
- API: `src/i4g/api/app.py` (FastAPI). Routers for reviews/search, tasks, ingestion, reports.
- Jobs/CLI: `i4g-admin`, `i4g-ingest-job`, `i4g-report-job`, `i4g-intake-job` (installed via editable install).
- Factories: `src/i4g/services/factories.py` for stores/retrievers (honor settings and env overrides).
- Data stores: structured store + SQL dual-write; default vector backend is Chroma.

## Repository layout
- `src/` — application code (API, workers, services, stores)
- `config/` — settings defaults and local overrides
- `docs/` — all guides, architecture, TDD, runbooks, cookbooks
- `scripts/` — tooling and bootstrap helpers
- `tests/` — unit and contract tests
- `reports/` — report templates and assets
- `data/` — local runtime artifacts (SQLite, Chroma, reports) created by bootstrap

## Contributing and governance
- Contribution guide: [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md); authors list: [docs/contributors.md](docs/contributors.md)
- Follow docs navigation via [docs/README.md](docs/README.md) and keep links updated when adding new pages.
- For infrastructure changes, see [infra/README.md](../infra/README.md).

## License

MIT. AI-generated components are for educational and research use only.
