"""Cloud Run job entrypoint for processing queued intake submissions."""

from __future__ import annotations

import logging
import sys
import urllib.parse
from typing import Any

import httpx
from google.auth.transport.requests import Request
from google.oauth2 import id_token

from i4g.services.intake import IntakeService
from i4g.services.intake_job_runner import LocalPipelineIntakeJobRunner
from i4g.settings import get_settings
from i4g.worker.logging import configure_job_logging

LOGGER = logging.getLogger("i4g.worker.jobs.intake")


def _safe_post(
    client: httpx.Client,
    path: str,
    payload: dict[str, Any],
    *,
    required: bool = True,
    log_context: str,
) -> httpx.Response | None:
    """
    Performs a POST request and handles errors gracefully.

    Args:
        client: The HTTP client to use.
        path: The URL path to post to.
        payload: The JSON payload to send.
        required: Whether to raise an exception on failure.
        log_context: Context string for logging.

    Returns:
        The response object if successful, None otherwise.
    """
    try:
        response = client.post(path, json=payload)
        response.raise_for_status()
        return response
    except httpx.HTTPStatusError as exc:
        if not required and exc.response.status_code == 404:
            LOGGER.warning("API resource missing during %s: %s", log_context, exc)
            return None
        raise


def _get_oidc_token(audience: str) -> str | None:
    """
    Fetch an OIDC token for the given audience if running in GCP.

    Args:
        audience: The target audience for the token.

    Returns:
        The OIDC token string, or None if it could not be fetched.
    """
    try:
        auth_req = Request()
        return id_token.fetch_id_token(auth_req, audience)
    except Exception as exc:
        # This is expected locally or if not running on GCP with proper identity
        LOGGER.debug("Could not fetch OIDC token for audience %s: %s", audience, exc)
        return None


def _process_via_api(intake_id: str, job_id: str, api_base: str, api_key: str | None) -> int:
    """
    Processes an intake job by communicating with the API.

    Args:
        intake_id: The ID of the intake record.
        job_id: The ID of the job.
        api_base: The base URL of the API.
        api_key: The API key for authentication.

    Returns:
        0 on success, 1 on failure.
    """
    runner = LocalPipelineIntakeJobRunner()
    headers = {"X-API-KEY": api_key} if api_key else {}

    # Attempt to inject OIDC token for Cloud Run service-to-service auth
    try:
        parsed = urllib.parse.urlparse(api_base)
        # Audience is typically the root URL (scheme + netloc)
        audience = f"{parsed.scheme}://{parsed.netloc}"
        token = _get_oidc_token(audience)
        if token:
            headers["Authorization"] = f"Bearer {token}"
    except Exception as exc:
        LOGGER.warning("Failed to configure OIDC auth: %s", exc)

    base = api_base.rstrip("/")
    with httpx.Client(base_url=base, headers=headers, timeout=30.0) as client:
        try:
            _safe_post(
                client,
                f"/jobs/{job_id}",
                {"status": "running", "message": "Processing intake", "metadata": {"runner": runner.name}},
                required=False,
                log_context="job status update (running)",
            )
            _safe_post(
                client,
                f"/{intake_id}/status",
                {"status": "processing", "message": "Ingestion started"},
                required=False,
                log_context="intake status update (processing)",
            )

            record_resp = client.get(f"/{intake_id}")
            record_resp.raise_for_status()
            record = record_resp.json()

            result = runner.run(record)
            metadata = dict(result.metadata or {})
            metadata.setdefault("runner", runner.name)
            metadata["case_id"] = result.case_id

            _safe_post(
                client,
                f"/{intake_id}/case",
                {"case_id": result.case_id, "review_id": None},
                required=False,
                log_context="case attachment",
            )
            _safe_post(
                client,
                f"/jobs/{job_id}",
                {"status": "completed", "message": result.message, "metadata": metadata},
                required=False,
                log_context="job status update (completed)",
            )
            _safe_post(
                client,
                f"/{intake_id}/status",
                {"status": "processed", "message": result.message},
                required=False,
                log_context="intake status update (processed)",
            )

            LOGGER.info(
                "Intake job completed successfully via API: intake_id=%s case_id=%s",
                intake_id,
                result.case_id,
            )
            return 0
        except Exception as exc:  # pragma: no cover - defensive logging for production failures
            LOGGER.exception("Intake job failed via API: intake_id=%s", intake_id)
            failure_payload = {"status": "failed", "message": str(exc)}
            try:
                _safe_post(
                    client,
                    f"/jobs/{job_id}",
                    failure_payload,
                    required=False,
                    log_context="job status update (failure)",
                )
                _safe_post(
                    client,
                    f"/{intake_id}/status",
                    {"status": "error", "message": str(exc)},
                    required=False,
                    log_context="intake status update (error)",
                )
            except Exception:  # pragma: no cover - best-effort failure reporting
                LOGGER.exception("Failed to report intake job failure to API")
            return 1


def main() -> int:
    """Entry point executed by the Cloud Run job container."""

    configure_job_logging()

    try:
        settings = get_settings()
    except Exception:
        LOGGER.exception("Unable to load settings for intake job")
        return 1

    intake_cfg = settings.intake
    intake_id = intake_cfg.id
    job_id = intake_cfg.job_id
    if not intake_id or not job_id:
        LOGGER.error("Both I4G_INTAKE__ID and I4G_INTAKE__JOB_ID environment variables are required")
        return 1

    LOGGER.info("Processing intake job: intake_id=%s job_id=%s", intake_id, job_id)

    api_base = intake_cfg.api_base
    if api_base:
        api_key = intake_cfg.api_key or settings.api.key
        return _process_via_api(intake_id, job_id, api_base, api_key)

    service = IntakeService()
    try:
        service.process_job(intake_id, job_id)
        LOGGER.info("Intake job completed successfully: intake_id=%s", intake_id)
        return 0
    except Exception:  # pragma: no cover - defensive logging for production failures
        LOGGER.exception("Intake job failed: intake_id=%s", intake_id)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
