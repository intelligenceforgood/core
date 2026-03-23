# ML Platform Inference — Deployment Runbook

How to switch the Core API from LLM-based classification to the ML Platform.

## Prerequisites

- ML serving container deployed to Cloud Run (`ml-serving` in `i4g-ml`)
- A model artifact uploaded to GCS (e.g., `gs://i4g-ml-data/models/classification/v1/`)
- Core service has network access to the ML Cloud Run service

## Configuration

The ML Platform client is controlled by the `[ml]` section in settings:

| Setting                | Default | Description                                    |
| ---------------------- | ------- | ---------------------------------------------- |
| `inference_backend`    | `llm`   | `llm` (existing) or `ml_platform` (ML service) |
| `platform_base_url`    | `""`    | Cloud Run ML serving URL                       |
| `platform_auth_method` | `iam`   | `iam`, `api_key`, or `none`                    |
| `fallback_to_llm`      | `true`  | Fall back to LLM if ML platform is unavailable |

### Environment Variables

Override per environment using `I4G_ML__*` env vars:

```bash
I4G_ML__INFERENCE_BACKEND=ml_platform
I4G_ML__PLATFORM_BASE_URL=https://ml-serving-21208516810.us-central1.run.app
I4G_ML__PLATFORM_AUTH_METHOD=iam
I4G_ML__FALLBACK_TO_LLM=true
```

## Switch to ML Platform (Dev)

1. **Verify the ML serving endpoint is healthy:**

   ```bash
   # Get an identity token via service account impersonation
   TOKEN=$(gcloud auth print-identity-token \
     --impersonate-service-account=sa-infra@i4g-ml.iam.gserviceaccount.com \
     --audiences=https://ml-serving-21208516810.us-central1.run.app)

   python3 -c "
   import urllib.request, json
   req = urllib.request.Request(
       'https://ml-serving-21208516810.us-central1.run.app/health',
       headers={'Authorization': 'Bearer $TOKEN'})
   resp = urllib.request.urlopen(req)
   print(json.loads(resp.read()))
   "
   ```

   Expected: `{"status": "healthy", "model_id": "..."}` or `{"status": "healthy", "model_id": null}` (stub mode).

2. **Set env vars on the Core Cloud Run service:**

   ```bash
   gcloud run services update core-svc \
     --project=i4g-dev \
     --region=us-central1 \
     --update-env-vars="I4G_ML__INFERENCE_BACKEND=ml_platform"
   ```

   Or add to `infra/stacks/app/main.tf` as an env var on the core-svc module.

3. **Verify classification uses ML platform:**

   Submit a test case through the UI or API and check the response includes ML platform prediction metadata.

## Rollback to LLM

Set `I4G_ML__INFERENCE_BACKEND=llm` (or remove the env var — `llm` is the default):

```bash
gcloud run services update core-svc \
  --project=i4g-dev \
  --region=us-central1 \
  --update-env-vars="I4G_ML__INFERENCE_BACKEND=llm"
```

## Loading a Real Model

To serve a trained model instead of stubs, set `MODEL_ARTIFACT_URI` on the ML serving service:

```bash
gcloud run services update ml-serving \
  --project=i4g-ml \
  --region=us-central1 \
  --update-env-vars="MODEL_ARTIFACT_URI=gs://i4g-ml-data/models/classification/v1/"
```

The model artifacts must include:

- `label_map.json` — maps axis names to label codes
- Either `model/` directory (PyTorch/Transformers) or `xgboost_model.json` (XGBoost)

## Monitoring

- Cloud Run logs: `gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=ml-serving" --project=i4g-ml --limit=20`
- Health endpoint: `GET /health` returns `healthy`, `degraded` (model load failed), or `unhealthy`
- Prediction endpoint: `POST /predict/classify` returns 503 when model load has failed
