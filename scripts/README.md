# Scripts Directory

This directory contains operational utilities and implementation logic for the `i4g` CLI.

## CLI Implementations
The following scripts contain the logic backing `i4g` CLI commands. They are imported by the CLI wrappers in `src/i4g/cli/` but can also be run directly for debugging.

(No standalone CLI implementation scripts remain; all logic has been moved to `src/i4g/cli/` subpackages.)

## Standalone Utilities
These scripts are not exposed via the `i4g` CLI and are used for CI, debugging, or specific infrastructure tasks.

- `build_image.sh`: Container/image build helper; run directly from repo root.
- `check_docs_snippets.py`: Scans markdown files for large code blocks to enforce documentation standards. Used in CI.
- `debug_iap.py`: Tests IAP authentication flows by impersonating a service account. Useful for verifying service-to-service auth.
- `debug_settings.py`: Validates Pydantic settings resolution and environment variable overrides. Useful for debugging configuration issues.
- `git-hooks/`: Local hook installer assets.
- `infra/`, `migration/`: Niche infrastructure or one-time migration helpers.
- `run_account_job.sh`: Entrypoint wrapper for the account list job container.

## Notes
- **CLI Usage**: Prefer using the `i4g` CLI commands over running these scripts directly.
- **Direct Usage**: If you must bypass the CLI, run scripts in the project environment: `conda run -n i4g python scripts/<name>.py ...`.
