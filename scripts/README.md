# Scripts Directory

- `build_image.sh`: Container/image build helper; run directly from repo root.
- `check_docs_snippets.py`: Scans markdown files for large code blocks to enforce documentation standards. Used in CI.
- `debug_iap.py`: Tests IAP authentication flows by impersonating a service account. Useful for verifying service-to-service auth.
- `debug_settings.py`: Validates Pydantic settings resolution and environment variable overrides. Useful for debugging configuration issues.
- `git-hooks/`: Local hook installer assets.
- `infra/`, `migration/`: Niche infrastructure or one-time migration helpers.
- `run_account_job.sh`: Entrypoint wrapper for the account list job container.
