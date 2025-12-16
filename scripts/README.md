# Scripts Directory

Most operational utilities now live behind the unified `i4g` CLI (see `i4g --help`). Prefer the CLI subcommands over calling Python files directly. The wrappers live in `src/i4g/cli/app.py` and mirror the legacy scripts under this folder.

## Standalone scripts (not in `i4g` CLI)
- `build_image.sh`: container/image build helper; run directly from repo root.
- `git-hooks/`: local hook installer assets; use `git config`/`ln -s` as needed, not part of the CLI.
- `infra/`, `migration/`: niche infrastructure or one-time migration helpers. Keep these separate from the public CLI surface.

## Notes
- Run Python scripts in the project environment: `conda run -n i4g python scripts/<name>.py ...` if you must bypass the CLI.
- For ingestion/report jobs, prefer the packaged entry points: `i4g jobs ingest|report|intake|account|ingest-retry|dossier`.
- Smoke checks: `i4g smoke dossiers|vertex-search|cloud-run`.
- Environment bootstrap: `i4g env bootstrap-local` and `i4g env seed-sample`.
-- One-time Azure migration scripts live under `scripts/migration/` and are not part of the public CLI; they remain only for archival data pulls.
