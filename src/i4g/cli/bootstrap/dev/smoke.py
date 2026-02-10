"""Cloud Run and IAP smoke helpers for dev bootstrap."""

from __future__ import annotations

import logging
import subprocess

import google.auth
import google.auth.impersonated_credentials
import google.auth.transport.requests
from googleapiclient.discovery import build

from i4g.cli.bootstrap.common import SmokeResult

from .constants import DEFAULT_RUNTIME_SA, IAP_CLIENT_ID_FALLBACK


def _get_iap_token(project: str, service_account: str | None) -> str | None:
    """Fetch an IAP-compatible ID token by looking up the backend service audience."""

    impersonate_sa = DEFAULT_RUNTIME_SA
    audience = None

    # 1. Authenticate (User credentials)
    try:
        source_creds, _ = google.auth.default()
        request = google.auth.transport.requests.Request()
        source_creds.refresh(request)
    except Exception as exc:
        logging.debug("Failed to get default credentials: %s", exc)
        return None

    # 2. Fetch the IAP Client ID (audience)
    try:
        service = build("compute", "v1", credentials=source_creds, cache_discovery=False)
        response = service.backendServices().get(project=project, backendService="i4g-lb-backend-api").execute()
        audience = response.get("iap", {}).get("oauth2ClientId")
    except Exception:
        pass

    if not audience:
        audience = IAP_CLIENT_ID_FALLBACK

    if not audience:
        return None

    # 3. Try to generate ID token via impersonation (preferred for CI/automation)
    try:
        compute_creds = google.auth.impersonated_credentials.Credentials(
            source_credentials=source_creds,
            target_principal=impersonate_sa,
            target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
            lifetime=3600,
        )
        id_token_creds = google.auth.impersonated_credentials.IDTokenCredentials(
            target_credentials=compute_creds, target_audience=audience, include_email=True
        )
        id_token_creds.refresh(request)
        return id_token_creds.token
    except Exception as exc:
        logging.debug("Impersonated IAP token generation failed: %s", exc)

    # 4. Fallback: Generate ID token using local user credentials
    try:
        proc = subprocess.run(
            ["gcloud", "auth", "print-identity-token", f"--audiences={audience}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except Exception as exc:
        logging.debug("Local gcloud IAP token generation failed: %s", exc)

    return None


def run_smoke(
    *,
    project: str,
    region: str,
    wif_service_account: str | None = None,
    smoke_api_url: str,
    smoke_token: str,
    smoke_job: str,
    smoke_container: str,
) -> SmokeResult:
    from i4g.cli import smoke

    iap_token = _get_iap_token(project, wif_service_account)

    try:
        smoke.cloud_run_smoke(
            api_url=smoke_api_url,
            token=smoke_token,
            project=project,
            region=region,
            job=smoke_job,
            container=smoke_container,
            iap_token=iap_token,
            impersonate_service_account=wif_service_account,
        )
    except SystemExit as exc:  # pragma: no cover - subprocess failure path
        return SmokeResult(status="failed", message=str(exc))
    return SmokeResult(status="success", message="Cloud Run intake smoke passed")
