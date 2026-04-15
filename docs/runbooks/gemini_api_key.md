# Gemini API Key Management

Operational runbook for creating, rotating, and troubleshooting Gemini API keys used by Core and SSI services.

## Background

Both Core and SSI call Gemini models via the `google-genai` SDK. When a Gemini API key is configured, the SDK uses `genai.Client(api_key=...)` which routes through `generativelanguage.googleapis.com`. This bills to the GCP project's billing account (non-profit). Without an API key, the SDK falls back to Vertex AI ADC (`vertexai=True`), which routes through `aiplatform.googleapis.com`.

## Prerequisites

- `gcloud` CLI authenticated with permissions on the target project
- Roles: `roles/serviceusage.serviceUsageAdmin` (enable APIs), `roles/secretmanager.admin` (manage secrets)

## Create a New API Key

### 1. Verify the Generative Language API is enabled

```bash
gcloud services list --enabled --project=<PROJECT_ID> \
  | grep generativelanguage
```

If missing, enable it (already done via Terraform for `i4g-dev` and `i4g-prod`):

```bash
gcloud services enable generativelanguage.googleapis.com --project=<PROJECT_ID>
```

### 2. Create the API key in GCP Console

One API key serves both Core and SSI — the key is just a string value, and each service receives it via its own env var from the same Secret Manager secret.

1. Open [APIs & Services → Credentials](https://console.cloud.google.com/apis/credentials) for the target project.
2. Click **Create Credentials → API key**.
3. Enter the key name (e.g., `gemini-api-key-dev`).
4. Check **Authenticate API calls through a service account**.
5. Click **+ Select a service account** and choose `sa-app@<PROJECT_ID>.iam.gserviceaccount.com`.
6. Scroll up to **Select API restrictions** — **Gemini API** should now be the only item listed. Select it.
7. Under **Restrict your key to reduce security risk** (application restrictions), leave **None** selected. Cloud Run IPs are dynamic, so IP-based restrictions don't apply. The SA binding and Gemini API restriction already scope this key.
8. Click **Create**.
9. Copy the key value from the confirmation dialog — it will not be shown again.

> **Why the service account binding?** For projects under a Google Cloud organization, GCP requires API keys to be bound to a service account before they can be restricted to Gemini APIs. The binding controls quota and permissions; it does not limit which service can use the key. Both Core (`sa-app`) and SSI (`sa-ssi`) can use the same key value — bind to `sa-app` as the primary runtime SA.

### 3. Store the key in Secret Manager

```bash
echo -n "<YOUR_API_KEY>" | gcloud secrets versions add gemini-api-key \
  --data-file=- --project=<PROJECT_ID>
```

If the secret doesn't exist yet (already created via Terraform):

```bash
gcloud secrets create gemini-api-key --replication-policy=automatic --project=<PROJECT_ID>
echo -n "<YOUR_API_KEY>" | gcloud secrets versions add gemini-api-key \
  --data-file=- --project=<PROJECT_ID>
```

### 4. Verify Cloud Run services pick up the new secret version

Cloud Run reads the **latest** secret version on each new container instance. To force a restart:

```bash
# Core
gcloud run services update core-svc --region=us-central1 --project=<PROJECT_ID>

# SSI
gcloud run services update ssi-svc --region=us-central1 --project=<PROJECT_ID>
```

## Rotate an Existing Key

1. Create a new API key (steps 2 above).
2. Add the new key as a new secret version (step 3).
3. Restart services (step 4) — they'll pick up the latest version.
4. Delete or disable the old API key in the Credentials console.

## Env Var Mapping

| Service | Secret Manager secret | Env var in Cloud Run      | Settings field       |
| ------- | --------------------- | ------------------------- | -------------------- |
| Core    | `gemini-api-key`      | `I4G_LLM__GEMINI_API_KEY` | `llm.gemini_api_key` |
| SSI     | `gemini-api-key`      | `SSI_LLM__GEMINI_API_KEY` | `llm.gemini_api_key` |

## Troubleshooting

| Symptom                             | Cause                                                                               | Fix                                                      |
| ----------------------------------- | ----------------------------------------------------------------------------------- | -------------------------------------------------------- |
| `403 PERMISSION_DENIED` from Gemini | API key restricted to wrong API, or `generativelanguage.googleapis.com` not enabled | Check key restrictions in Console; verify API is enabled |
| `400 API_KEY_INVALID`               | Stale or deleted key                                                                | Rotate key (see above)                                   |
| Billing on personal credit card     | Using Vertex AI ADC fallback (no API key set)                                       | Set `gemini_api_key` and restart services                |
| Pydantic `extra_forbidden` crash    | Env var set but code doesn't have the `gemini_api_key` field                        | Deploy updated image first, then wire env var            |

## Local Development

Local dev uses `I4G_LLM__PROVIDER=ollama` by default and does not need a Gemini API key. If you want to test against the real Gemini API locally:

```bash
export I4G_LLM__PROVIDER=gemini
export I4G_LLM__GEMINI_API_KEY="<YOUR_API_KEY>"
export I4G_LLM__CHAT_MODEL="gemini-3-flash-preview"
```
