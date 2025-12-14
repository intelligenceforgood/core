# Bootstrap or Refresh the Local Sandbox

Use this when you need a clean local dataset (SQLite + Chroma) for development, smokes, or demos.

## Prerequisites
- Conda env `i4g` available.
- From repo root `core/`.

## Steps (full reset)
```bash
conda run -n i4g python scripts/bootstrap_local_sandbox.py --reset
```
- Seeds SQLite stores, Chroma vector store, and sample data under `data/`.
- Uses defaults from `config/settings.default.toml`; override via `config/settings.local.toml` or `I4G_*` env vars.

## Partial rebuilds
- Skip expensive pieces with flags, for example:
```bash
conda run -n i4g python scripts/bootstrap_local_sandbox.py --reset --skip-ocr --skip-chroma
```

## After running
- Point ingestion/search to the refreshed data (default dataset in settings: `ingestion.default_dataset`).
- Run a quick smoke: [smoke_test.md](smoke_test.md).

## Notes
- Avoid hand-editing `data/`—rerun the bootstrap script for reproducibility.
- If you change settings or paths, keep `config/settings.local.toml` in sync and regenerate manifests if needed (`scripts/export_settings_manifest.py`).
