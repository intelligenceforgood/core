"""Cloud Run job entrypoint for scheduled account list extraction."""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone

from i4g.services.account_list import AccountListRequest, AccountListResult, AccountListService, log_account_list_run
from i4g.settings import Settings, get_settings
from i4g.utils.datetime_parse import parse_datetime
from i4g.worker.logging import configure_job_logging

LOGGER = logging.getLogger("i4g.worker.jobs.account_list")
_DEFAULT_FORMATS = ["xlsx", "pdf"]


def _parse_datetime(value: str) -> datetime:  # noqa: D103 — thin wrapper around shared parse_datetime
    result = parse_datetime(value, on_error="raise")
    return result.astimezone(timezone.utc)


def _resolve_formats(settings: Settings) -> list[str]:
    job = settings.account_job
    if job.output_formats:
        return job.output_formats
    if settings.account_list.default_formats:
        return [item.lower() for item in settings.account_list.default_formats if item]
    return list(_DEFAULT_FORMATS)


def _build_request_from_env(settings: Settings, *, now: datetime | None = None) -> AccountListRequest:
    reference = now or datetime.now(timezone.utc)
    job = settings.account_job

    window_days = job.window_days
    if window_days <= 0:
        raise ValueError("I4G_ACCOUNT_JOB__WINDOW_DAYS must be positive")

    end_time = _parse_datetime(job.end_time) if job.end_time else reference
    start_time = _parse_datetime(job.start_time) if job.start_time else end_time - timedelta(days=window_days)

    top_k = min(job.top_k, settings.account_list.max_top_k)
    output_formats = _resolve_formats(settings)

    return AccountListRequest(
        start_time=start_time,
        end_time=end_time,
        categories=job.categories,
        top_k=top_k,
        include_sources=job.include_sources,
        output_formats=output_formats,
    )


def _build_service() -> AccountListService:
    return AccountListService()


def _log_result_summary(result: AccountListResult, *, actor: str) -> None:
    LOGGER.info(
        "Account list run %s completed by %s: indicators=%s sources=%s warnings=%s",
        result.request_id,
        actor,
        len(result.indicators),
        len(result.sources),
        len(result.warnings),
    )
    if result.artifacts:
        LOGGER.info("Artifacts generated: %s", result.artifacts)
    if result.warnings:
        LOGGER.warning("Warnings: %s", "; ".join(result.warnings))


def main() -> int:
    """Entry point executed by the Cloud Run job container."""

    try:
        settings = get_settings()
    except Exception:
        LOGGER.exception("Unable to load settings for account job")
        return 1
    configure_job_logging(settings)
    actor = f"account_job:{getattr(settings, 'env', 'unknown')}"

    try:
        request = _build_request_from_env(settings)
    except ValueError as exc:
        LOGGER.error("Invalid account job configuration: %s", exc)
        return 1

    dry_run = settings.account_job.dry_run
    LOGGER.info(
        "Starting account list job: top_k=%s window=%s→%s categories=%s formats=%s dry_run=%s",
        request.top_k,
        request.start_time,
        request.end_time,
        request.categories or ["bank", "crypto", "payments"],
        request.output_formats,
        dry_run,
    )

    if dry_run:
        LOGGER.info("Dry run enabled; skipping execution.")
        return 0

    service = _build_service()

    try:
        result = service.run(request)
    except Exception:
        LOGGER.exception("Account list extraction failed")
        return 1

    _log_result_summary(result, actor=actor)
    try:
        log_account_list_run(actor=actor, source="worker", result=result)
    except Exception:  # pragma: no cover - defensive path
        LOGGER.exception(
            "Failed to write account list audit entry",
            extra={"request_id": result.request_id},
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
