# Retention Purge Runbook

> **Status**: Active (v1.0)
> **Last Updated**: February 2026

Operate the automated retention-purge job that soft-deletes resolved cases and hard-purges them after a grace period.

## Overview

The retention pipeline runs in two phases:

1. **Soft-delete** — Cases in a resolved status (`closed`, `accepted`, `rejected`) whose `resolved_at` timestamp exceeds `retention_days` are marked `is_deleted = true` with a `deleted_at` timestamp.
2. **Hard-purge** — Soft-deleted cases older than `retention_grace_days` are permanently removed along with their related data (source documents, entities, indicators, review queue entries, scam/intake records, PII vault tokens, evidence files, and vector embeddings).

## Settings Reference

| Setting                        | Env Var                             | Default | Purpose                                                        |
| :----------------------------- | :---------------------------------- | :------ | :------------------------------------------------------------- |
| `storage.retention_enabled`    | `I4G_STORAGE__RETENTION_ENABLED`    | `true`  | Master kill-switch. Set to `false` to skip all purge activity. |
| `storage.retention_days`       | `I4G_STORAGE__RETENTION_DAYS`       | `90`    | Days after case resolution before soft-delete.                 |
| `storage.retention_grace_days` | `I4G_STORAGE__RETENTION_GRACE_DAYS` | `30`    | Days after soft-delete before hard-purge.                      |

> **Local override**: `config/settings.local.toml` ships with `retention_enabled = false` to prevent accidental purge during development.

## Running the Job

### Local (dry-run)

```bash
conda run -n i4g \
  I4G_PROJECT_ROOT=$PWD \
  I4G_ENV=dev \
  I4G_LLM__PROVIDER=mock \
  I4G_STORAGE__RETENTION_ENABLED=true \
  i4g jobs retention-purge --dry-run
```

The `--dry-run` flag logs which cases **would** be affected without writing any changes.

### Local (live)

```bash
conda run -n i4g \
  I4G_PROJECT_ROOT=$PWD \
  I4G_ENV=dev \
  I4G_LLM__PROVIDER=mock \
  I4G_STORAGE__RETENTION_ENABLED=true \
  i4g jobs retention-purge
```

### Cloud Run (scheduled)

The `retention_purge` Cloud Run job is configured in `infra/environments/app/dev/terraform.tfvars` with a Cloud Scheduler cron (`0 3 * * *` — daily at 03:00 UTC). The job reads `I4G_STORAGE__RETENTION_DAYS` and `I4G_STORAGE__RETENTION_GRACE_DAYS` from its environment variables.

## Disabling Purge

Set the env var on the Cloud Run job or in the TOML config:

```bash
# Via env var (Cloud Run or shell)
I4G_STORAGE__RETENTION_ENABLED=false

# Via config/settings.local.toml
[storage]
retention_enabled = false
```

When disabled, the job exits immediately with code 0 and logs `"Retention purge is disabled via settings — skipping."`.

## GDPR Endpoints

Two admin-only API endpoints support individual data-subject requests:

| Method   | Path                      | Purpose                                                         |
| :------- | :------------------------ | :-------------------------------------------------------------- |
| `GET`    | `/cases/{case_id}/export` | Export all case data as JSON (data portability).                |
| `DELETE` | `/cases/{case_id}`        | Immediately and permanently delete a case and all related data. |

Both require the `admin` role. The `DELETE` endpoint bypasses the retention window — it hard-purges immediately regardless of `retention_days` or `retention_grace_days`.

## Troubleshooting

| Symptom                                   | Check                                                                                                                                                    |
| :---------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Job exits immediately, no cases processed | Verify `I4G_STORAGE__RETENTION_ENABLED=true` in the job's environment.                                                                                   |
| Cases not being soft-deleted              | Ensure cases have a `resolved_at` timestamp and a resolved status.                                                                                       |
| Hard-purge not removing evidence files    | Check `I4G_STORAGE__EVIDENCE_BUCKET` or `evidence_local_dir` settings; verify the service account has `storage.objects.delete` permission on the bucket. |
| PII tokens not deleted                    | Verify PII vault connectivity (`I4G_PII__BACKEND`, `I4G_PII__CLOUDSQL_*`). The job logs warnings but does not abort if the vault is unreachable.         |

## Related

- Settings manifest: [docs/config/README.md](../config/README.md)
- Design: [docs/design/storage.md](../design/storage.md), [docs/compliance.md](../compliance.md)
- Jobs inventory: [docs/design/jobs.md](../design/jobs.md)
- Source: `src/i4g/services/retention.py`, `src/i4g/worker/jobs/retention_purge.py`
