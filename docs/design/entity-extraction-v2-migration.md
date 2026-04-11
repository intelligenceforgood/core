# Entity Extraction v2 — Production Migration Runbook

> **Created**: 2026-04-10
> **Audience**: Engineering team performing the migration

---

## Prerequisites

- All Sprint 1–5 code is merged to `main`
- Dev environment is deployed with the latest `core-svc` image
- `regression-v1` bundle exists locally (`i4g entity-qa bundle list`)

---

## Step 1: Baseline Current Quality on Dev

Run the score command against dev DB entities to measure current (pre-migration) quality:

```bash
conda run -n i4g i4g entity-qa score \
    --bundle regression-v1 \
    --save \
    --format text
```

Save the output. This is the **before** snapshot.

---

## Step 2: Run Orchestrator Backfill on Dev

Re-extract all cases using the v2 orchestrator:

```bash
conda run -n i4g I4G_PROJECT_ROOT=$PWD I4G_ENV=dev \
    I4G_LLM__PROVIDER=vertex_ai \
    i4g jobs entity-extract --backfill --limit 0
```

> **Note:** `--backfill` re-extracts all cases. Existing entities are preserved via
> `ON CONFLICT DO NOTHING` — new entity types and improved extractions are added alongside.

Monitor progress via the job's task status output.

---

## Step 3: Score After Backfill

```bash
conda run -n i4g i4g entity-qa score \
    --bundle regression-v1 \
    --save \
    --format text
```

Compare with Step 1 output. The report shows regression deltas automatically.

---

## Step 4: Decision Gate

| Outcome                                      | Action                                                                             |
| -------------------------------------------- | ---------------------------------------------------------------------------------- |
| F1 improves or holds steady across all types | Proceed to prod deployment                                                         |
| F1 regresses on any type                     | Investigate. Adjust gates/authority in `settings.default.toml`. Re-run from Step 2 |
| New entity types appear with acceptable F1   | Good — v2 extracts types v1 missed                                                 |

---

## Step 5: Deploy to Prod

Build and deploy the latest core-svc image:

```bash
scripts/build_image.sh core-svc prod
scripts/build_image.sh entity-extract-job prod
```

Then deploy via Terraform or Cloud Console.

---

## Step 6: Run Orchestrator Backfill on Prod

```bash
# Trigger via Cloud Scheduler or manual Cloud Run job execution
gcloud run jobs execute entity-extract-job \
    --region us-central1 \
    --project i4g-prod \
    --update-env-vars I4G_EXTRACTION__BACKFILL=true
```

---

## Step 7: Validate Prod Quality

Pull a sample of re-extracted cases and spot-check:

- Do previously misclassified entities (Wells Fargo as person, etc.) no longer appear?
- Do new entity types (scam_indicator, domain) appear correctly?
- Are merge logs showing expected audit decisions?

---

## Rollback

If quality regresses in production:

1. The backfill does NOT delete existing entities — old extractions are preserved
2. Revert the `enabled_modules` setting to `["regex"]` to disable LLM extraction
3. Re-deploy with the previous image tag
