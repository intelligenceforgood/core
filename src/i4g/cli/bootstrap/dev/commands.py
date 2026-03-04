"""Typer commands for ``i4g bootstrap dev``."""

from __future__ import annotations

import os
from pathlib import Path

import typer

from .constants import (
    DEFAULT_JOBS,
    DEFAULT_PROJECT,
    DEFAULT_REGION,
    DEFAULT_REPORT_DIR,
    DEFAULT_SMOKE_API_URL,
    DEFAULT_WIF_SA,
)
from .orchestrator import run_dev

dev_app = typer.Typer(help="Bootstrap dev via Cloud Run jobs and optional smokes.")


def _exit_from_return(code: int | None) -> None:
    """Honor integer return codes from invoked helpers."""

    if isinstance(code, int) and code != 0:
        raise typer.Exit(code)


@dev_app.command("reset", help="Run dev bootstrap jobs (Cloud Run) with optional smoke.")
def bootstrap_dev_reset(
    project: str = typer.Option(DEFAULT_PROJECT, "--project", help="Target GCP project (default: i4g-dev)."),
    region: str = typer.Option(DEFAULT_REGION, "--region", help="Cloud Run region (default: us-central1)."),
    bundle: str | None = typer.Option(None, "--bundle", help="Name of a specific bundle to process."),
    bundle_uri: str | None = typer.Option(None, "--bundle-uri", help="Bundle URI passed to jobs, if supported."),
    dataset: str | None = typer.Option(None, "--dataset", help="Dataset identifier injected into job args."),
    limit: int = typer.Option(0, "--limit", help="Limit the number of records to ingest (0 = unlimited)."),
    wif_service_account: str = typer.Option(
        DEFAULT_WIF_SA,
        "--wif-service-account",
        help="Service account to impersonate via WIF.",
    ),
    ingest_job: str = typer.Option(DEFAULT_JOBS["ingest"], "--ingest-job", help="Ingestion job name."),
    vertex_job: str = typer.Option(DEFAULT_JOBS["vertex"], "--vertex-job", help="Vertex import job.", hidden=True),
    sql_job: str = typer.Option(DEFAULT_JOBS["sql"], "--sql-job", help="Cloud SQL sync job.", hidden=True),
    bigquery_job: str = typer.Option(
        DEFAULT_JOBS["bigquery"], "--bigquery-job", help="BigQuery refresh job.", hidden=True
    ),
    gcs_assets_job: str = typer.Option(
        DEFAULT_JOBS["gcs_assets"], "--gcs-assets-job", help="GCS asset sync job.", hidden=True
    ),
    reports_job: str = typer.Option(
        DEFAULT_JOBS["reports"], "--reports-job", help="Reports/dossiers job.", hidden=True
    ),
    saved_searches_job: str = typer.Option(
        DEFAULT_JOBS["saved_searches"], "--saved-searches-job", help="Saved searches/tag presets job.", hidden=True
    ),
    seed_reviews_job: str = typer.Option(
        DEFAULT_JOBS["seed_reviews"], "--seed-reviews-job", help="Seed reviews job.", hidden=True
    ),
    skip_ingest: bool = typer.Option(False, "--skip-ingest", help="Skip ingestion job."),
    skip_vertex: bool = typer.Option(False, "--skip-vertex", help="Skip Vertex import job."),
    skip_vector: bool = typer.Option(False, "--skip-vector", help="Alias for --skip-vertex (for local parity)."),
    skip_sql: bool = typer.Option(False, "--skip-sql", help="Skip Cloud SQL sync job."),
    skip_bigquery: bool = typer.Option(False, "--skip-bigquery", help="Skip BigQuery refresh job."),
    skip_gcs_assets: bool = typer.Option(False, "--skip-gcs-assets", help="Skip GCS asset sync job."),
    skip_reports: bool = typer.Option(False, "--skip-reports", help="Skip reports/dossiers job."),
    skip_saved_searches: bool = typer.Option(False, "--skip-saved-searches", help="Skip saved searches job."),
    skip_seed_reviews: bool = typer.Option(False, "--skip-seed-reviews", help="Skip seed reviews job."),
    skip_ocr: bool = typer.Option(False, "--skip-ocr", help="Skip OCR test images bundle."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print planned commands without executing."),
    ingest_dry_run: bool = typer.Option(
        False, "--ingest-dry-run", help="Run ingestion in dry-run mode (skip DB writes)."
    ),
    run_smoke: bool = typer.Option(False, "--run-smoke/--no-run-smoke", help="Run Cloud Run intake smoke."),
    run_dossier_smoke: bool = typer.Option(
        False, "--run-dossier-smoke/--no-run-dossier-smoke", help="Run dossier verification smoke."
    ),
    run_search_smoke: bool = typer.Option(
        False, "--run-search-smoke/--no-run-search-smoke", help="Run Vertex search smoke."
    ),
    search_project: str | None = typer.Option(
        None, "--search-project", help="Vertex project for search smoke (defaults to --project)."
    ),
    search_location: str | None = typer.Option(
        None, "--search-location", help="Vertex location for search smoke (default from orchestrator)."
    ),
    search_data_store_id: str | None = typer.Option(
        None, "--search-data-store-id", help="Vertex data store id for search smoke."
    ),
    search_serving_config_id: str = typer.Option(
        "default_search", "--search-serving-config-id", help="Vertex serving config id for search smoke."
    ),
    search_query: str = typer.Option("wallet address verification", "--search-query", help="Search smoke query."),
    search_page_size: int = typer.Option(5, "--search-page-size", help="Result page size for search smoke."),
    report_dir: Path = typer.Option(
        DEFAULT_REPORT_DIR, "--report-dir", help="Directory to write JSON/Markdown reports."
    ),
    force: bool = typer.Option(False, "--force", help="Allow targeting non-dev projects (never prod)."),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging verbosity (DEBUG/INFO/WARNING/ERROR)."),
    smoke_api_url: str = typer.Option(
        os.getenv("I4G_SMOKE_API_URL", DEFAULT_SMOKE_API_URL),
        "--smoke-api-url",
        help="API base URL for smoke.",
    ),
    smoke_token: str = typer.Option(
        os.getenv("I4G_SMOKE_TOKEN", "dev-analyst-token"), "--smoke-token", help="API token for smoke."
    ),
    smoke_job: str = typer.Option(
        os.getenv("I4G_SMOKE_JOB", "process-intakes"),
        "--smoke-job",
        help="Cloud Run job to execute for smoke.",
        hidden=True,
    ),
    smoke_container: str = typer.Option(
        os.getenv("I4G_SMOKE_CONTAINER", "container-0"),
        "--smoke-container",
        help="Container for smoke job.",
        hidden=True,
    ),
    local_execution: bool = typer.Option(
        False, "--local-execution", help="Run ingestion logic locally instead of triggering Cloud Run jobs."
    ),
    rate_limit_delay: float = typer.Option(
        0.0, "--rate-limit-delay", help="Delay in seconds between records during ingestion (for rate limiting)."
    ),
    timeout: int = typer.Option(3600, "--timeout", help="Timeout in seconds for Cloud Run jobs."),
    verify_only: bool = typer.Option(
        False, "--verify-only", help="Skip job execution and only run verification smokes."
    ),
) -> None:
    """Execute dev Cloud Run bootstrap jobs; optional smoke after run."""

    if skip_vector:
        skip_vertex = True

    _exit_from_return(
        run_dev(
            project=project,
            region=region,
            bundle=bundle,
            bundle_uri=bundle_uri,
            dataset=dataset,
            wif_service_account=wif_service_account,
            ingest_job=ingest_job,
            vertex_job=vertex_job,
            sql_job=sql_job,
            bigquery_job=bigquery_job,
            gcs_assets_job=gcs_assets_job,
            reports_job=reports_job,
            saved_searches_job=saved_searches_job,
            seed_reviews_job=seed_reviews_job,
            skip_ingest=skip_ingest,
            skip_vertex=skip_vertex,
            skip_sql=skip_sql,
            skip_bigquery=skip_bigquery,
            skip_gcs_assets=skip_gcs_assets,
            skip_reports=skip_reports,
            skip_saved_searches=skip_saved_searches,
            skip_seed_reviews=skip_seed_reviews,
            skip_ocr=skip_ocr,
            dry_run=dry_run,
            ingest_dry_run=ingest_dry_run,
            verify_only=verify_only,
            run_smoke=run_smoke,
            run_dossier_smoke=run_dossier_smoke,
            run_search_smoke=run_search_smoke,
            search_project=search_project,
            search_location=search_location,
            search_data_store_id=search_data_store_id,
            search_serving_config_id=search_serving_config_id,
            search_query=search_query,
            search_page_size=search_page_size,
            report_dir=report_dir,
            force=force,
            log_level=log_level,
            smoke_api_url=smoke_api_url,
            smoke_token=smoke_token,
            smoke_job=smoke_job,
            smoke_container=smoke_container,
            local_execution=local_execution,
            limit=limit,
            rate_limit_delay=rate_limit_delay,
            timeout=f"{timeout}s",
        )
    )


@dev_app.command("load", help="Alias of reset for dev bootstrap jobs.")
def bootstrap_dev_load(
    project: str = typer.Option(DEFAULT_PROJECT, "--project", help="Target GCP project (default: i4g-dev)."),
    region: str = typer.Option(DEFAULT_REGION, "--region", help="Cloud Run region (default: us-central1)."),
    bundle: str | None = typer.Option(None, "--bundle", help="Name of a specific bundle to process."),
    bundle_uri: str | None = typer.Option(None, "--bundle-uri", help="Bundle URI passed to jobs, if supported."),
    dataset: str | None = typer.Option(None, "--dataset", help="Dataset identifier injected into job args."),
    limit: int = typer.Option(0, "--limit", help="Limit the number of records to ingest (0 = unlimited)."),
    wif_service_account: str = typer.Option(
        DEFAULT_WIF_SA,
        "--wif-service-account",
        help="Service account to impersonate via WIF.",
    ),
    ingest_job: str = typer.Option(DEFAULT_JOBS["ingest"], "--ingest-job", help="Ingestion job name."),
    vertex_job: str = typer.Option(DEFAULT_JOBS["vertex"], "--vertex-job", help="Vertex import job.", hidden=True),
    sql_job: str = typer.Option(DEFAULT_JOBS["sql"], "--sql-job", help="Cloud SQL sync job.", hidden=True),
    bigquery_job: str = typer.Option(
        DEFAULT_JOBS["bigquery"], "--bigquery-job", help="BigQuery refresh job.", hidden=True
    ),
    gcs_assets_job: str = typer.Option(
        DEFAULT_JOBS["gcs_assets"], "--gcs-assets-job", help="GCS asset sync job.", hidden=True
    ),
    reports_job: str = typer.Option(
        DEFAULT_JOBS["reports"], "--reports-job", help="Reports/dossiers job.", hidden=True
    ),
    saved_searches_job: str = typer.Option(
        DEFAULT_JOBS["saved_searches"], "--saved-searches-job", help="Saved searches/tag presets job.", hidden=True
    ),
    seed_reviews_job: str = typer.Option(
        DEFAULT_JOBS["seed_reviews"], "--seed-reviews-job", help="Seed reviews job.", hidden=True
    ),
    skip_ingest: bool = typer.Option(False, "--skip-ingest", help="Skip ingestion job."),
    skip_vertex: bool = typer.Option(False, "--skip-vertex", help="Skip Vertex import job."),
    skip_vector: bool = typer.Option(False, "--skip-vector", help="Alias for --skip-vertex (for local parity)."),
    skip_sql: bool = typer.Option(False, "--skip-sql", help="Skip Cloud SQL sync job."),
    skip_bigquery: bool = typer.Option(False, "--skip-bigquery", help="Skip BigQuery refresh job."),
    skip_gcs_assets: bool = typer.Option(False, "--skip-gcs-assets", help="Skip GCS asset sync job."),
    skip_reports: bool = typer.Option(False, "--skip-reports", help="Skip reports/dossiers job."),
    skip_saved_searches: bool = typer.Option(False, "--skip-saved-searches", help="Skip saved searches job."),
    skip_seed_reviews: bool = typer.Option(False, "--skip-seed-reviews", help="Skip seed reviews job."),
    skip_ocr: bool = typer.Option(False, "--skip-ocr", help="Skip OCR test images bundle."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print planned commands without executing."),
    ingest_dry_run: bool = typer.Option(
        False, "--ingest-dry-run", help="Run ingestion in dry-run mode (skip DB writes)."
    ),
    run_smoke: bool = typer.Option(False, "--run-smoke/--no-run-smoke", help="Run Cloud Run intake smoke."),
    run_dossier_smoke: bool = typer.Option(
        False, "--run-dossier-smoke/--no-run-dossier-smoke", help="Run dossier verification smoke."
    ),
    run_search_smoke: bool = typer.Option(
        False, "--run-search-smoke/--no-run-search-smoke", help="Run Vertex search smoke."
    ),
    search_project: str | None = typer.Option(
        None, "--search-project", help="Vertex project for search smoke (defaults to --project)."
    ),
    search_location: str | None = typer.Option(
        None, "--search-location", help="Vertex location for search smoke (default from orchestrator)."
    ),
    search_data_store_id: str | None = typer.Option(
        None, "--search-data-store-id", help="Vertex data store id for search smoke."
    ),
    search_serving_config_id: str = typer.Option(
        "default_search", "--search-serving-config-id", help="Vertex serving config id for search smoke."
    ),
    search_query: str = typer.Option("wallet address verification", "--search-query", help="Search smoke query."),
    search_page_size: int = typer.Option(5, "--search-page-size", help="Result page size for search smoke."),
    report_dir: Path = typer.Option(
        DEFAULT_REPORT_DIR, "--report-dir", help="Directory to write JSON/Markdown reports."
    ),
    force: bool = typer.Option(False, "--force", help="Allow targeting non-dev projects (never prod)."),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging verbosity (DEBUG/INFO/WARNING/ERROR)."),
    smoke_api_url: str = typer.Option(
        os.getenv("I4G_SMOKE_API_URL", DEFAULT_SMOKE_API_URL),
        "--smoke-api-url",
        help="API base URL for smoke.",
    ),
    smoke_token: str = typer.Option(
        os.getenv("I4G_SMOKE_TOKEN", "dev-analyst-token"), "--smoke-token", help="API token for smoke."
    ),
    smoke_job: str = typer.Option(
        os.getenv("I4G_SMOKE_JOB", "process-intakes"),
        "--smoke-job",
        help="Cloud Run job to execute for smoke.",
        hidden=True,
    ),
    smoke_container: str = typer.Option(
        os.getenv("I4G_SMOKE_CONTAINER", "container-0"),
        "--smoke-container",
        help="Container for smoke job.",
        hidden=True,
    ),
    local_execution: bool = typer.Option(
        False, "--local-execution", help="Run ingestion logic locally instead of triggering Cloud Run jobs."
    ),
    rate_limit_delay: float = typer.Option(
        0.0, "--rate-limit-delay", help="Delay in seconds between records during ingestion (for rate limiting)."
    ),
    timeout: int = typer.Option(3600, "--timeout", help="Timeout in seconds for Cloud Run jobs."),
) -> None:
    """Alias of reset for dev bootstrap jobs (kept for symmetry)."""

    if skip_vector:
        skip_vertex = True

    _exit_from_return(
        run_dev(
            project=project,
            region=region,
            bundle=bundle,
            bundle_uri=bundle_uri,
            dataset=dataset,
            wif_service_account=wif_service_account,
            ingest_job=ingest_job,
            vertex_job=vertex_job,
            sql_job=sql_job,
            bigquery_job=bigquery_job,
            gcs_assets_job=gcs_assets_job,
            reports_job=reports_job,
            saved_searches_job=saved_searches_job,
            seed_reviews_job=seed_reviews_job,
            skip_ingest=skip_ingest,
            skip_vertex=skip_vertex,
            skip_sql=skip_sql,
            skip_bigquery=skip_bigquery,
            skip_gcs_assets=skip_gcs_assets,
            skip_reports=skip_reports,
            skip_saved_searches=skip_saved_searches,
            skip_seed_reviews=skip_seed_reviews,
            skip_ocr=skip_ocr,
            dry_run=dry_run,
            ingest_dry_run=ingest_dry_run,
            verify_only=False,
            run_smoke=run_smoke,
            run_dossier_smoke=run_dossier_smoke,
            run_search_smoke=run_search_smoke,
            search_project=search_project,
            search_location=search_location,
            search_data_store_id=search_data_store_id,
            search_serving_config_id=search_serving_config_id,
            search_query=search_query,
            search_page_size=search_page_size,
            report_dir=report_dir,
            force=force,
            log_level=log_level,
            smoke_api_url=smoke_api_url,
            smoke_token=smoke_token,
            smoke_job=smoke_job,
            smoke_container=smoke_container,
            local_execution=local_execution,
            limit=limit,
            rate_limit_delay=rate_limit_delay,
            timeout=f"{timeout}s",
        )
    )


@dev_app.command("verify", help="Run verification-only flow for dev (smoke optional).")
def bootstrap_dev_verify(
    project: str = typer.Option(DEFAULT_PROJECT, "--project", help="Target GCP project (default: i4g-dev)."),
    region: str = typer.Option(DEFAULT_REGION, "--region", help="Cloud Run region (default: us-central1)."),
    bundle: str | None = typer.Option(None, "--bundle", help="Name of a specific bundle to process."),
    bundle_uri: str | None = typer.Option(None, "--bundle-uri", help="Bundle URI passed to jobs, if supported."),
    dataset: str | None = typer.Option(None, "--dataset", help="Dataset identifier injected into job args."),
    wif_service_account: str = typer.Option(
        DEFAULT_WIF_SA,
        "--wif-service-account",
        help="Service account to impersonate via WIF.",
    ),
    vertex_job: str = typer.Option(DEFAULT_JOBS["vertex"], "--vertex-job", help="Vertex import job."),
    sql_job: str = typer.Option(DEFAULT_JOBS["sql"], "--sql-job", help="Cloud SQL sync job."),
    bigquery_job: str = typer.Option(DEFAULT_JOBS["bigquery"], "--bigquery-job", help="BigQuery refresh job."),
    gcs_assets_job: str = typer.Option(DEFAULT_JOBS["gcs_assets"], "--gcs-assets-job", help="GCS asset sync job."),
    reports_job: str = typer.Option(DEFAULT_JOBS["reports"], "--reports-job", help="Reports/dossiers job."),
    saved_searches_job: str = typer.Option(
        DEFAULT_JOBS["saved_searches"], "--saved-searches-job", help="Saved searches/tag presets job."
    ),
    seed_reviews_job: str = typer.Option(DEFAULT_JOBS["seed_reviews"], "--seed-reviews-job", help="Seed reviews job."),
    run_smoke: bool = typer.Option(True, "--run-smoke/--no-run-smoke", help="Run Cloud Run intake smoke."),
    run_dossier_smoke: bool = typer.Option(
        True, "--run-dossier-smoke/--no-run-dossier-smoke", help="Run dossier verification smoke."
    ),
    run_search_smoke: bool = typer.Option(
        True, "--run-search-smoke/--no-run-search-smoke", help="Run Vertex search smoke."
    ),
    search_project: str | None = typer.Option(
        None, "--search-project", help="Vertex project for search smoke (defaults to --project)."
    ),
    search_location: str | None = typer.Option(
        None, "--search-location", help="Vertex location for search smoke (default from orchestrator)."
    ),
    search_data_store_id: str | None = typer.Option(
        None, "--search-data-store-id", help="Vertex data store id for search smoke."
    ),
    search_serving_config_id: str = typer.Option(
        "default_search", "--search-serving-config-id", help="Vertex serving config id for search smoke."
    ),
    search_query: str = typer.Option("wallet address verification", "--search-query", help="Search smoke query."),
    search_page_size: int = typer.Option(5, "--search-page-size", help="Result page size for search smoke."),
    report_dir: Path = typer.Option(
        DEFAULT_REPORT_DIR, "--report-dir", help="Directory to write JSON/Markdown reports."
    ),
    force: bool = typer.Option(False, "--force", help="Allow targeting non-dev projects (never prod)."),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging verbosity (DEBUG/INFO/WARNING/ERROR)."),
    smoke_api_url: str = typer.Option(
        os.getenv("I4G_SMOKE_API_URL", DEFAULT_SMOKE_API_URL),
        "--smoke-api-url",
        help="API base URL for smoke.",
    ),
    smoke_token: str = typer.Option(
        os.getenv("I4G_SMOKE_TOKEN", "dev-analyst-token"), "--smoke-token", help="API token for smoke."
    ),
    smoke_job: str = typer.Option(
        os.getenv("I4G_SMOKE_JOB", "process-intakes"), "--smoke-job", help="Cloud Run job to execute for smoke."
    ),
    smoke_container: str = typer.Option(
        os.getenv("I4G_SMOKE_CONTAINER", "container-0"), "--smoke-container", help="Container for smoke job."
    ),
) -> None:
    """Skip job execution and only run verification/smoke for dev."""

    _exit_from_return(
        run_dev(
            project=project,
            region=region,
            bundle=bundle,
            bundle_uri=bundle_uri,
            dataset=dataset,
            wif_service_account=wif_service_account,
            vertex_job=vertex_job,
            sql_job=sql_job,
            bigquery_job=bigquery_job,
            gcs_assets_job=gcs_assets_job,
            reports_job=reports_job,
            saved_searches_job=saved_searches_job,
            seed_reviews_job=seed_reviews_job,
            skip_vertex=False,
            skip_sql=False,
            skip_bigquery=False,
            skip_gcs_assets=False,
            skip_reports=False,
            skip_saved_searches=False,
            skip_seed_reviews=False,
            skip_ocr=False,
            dry_run=False,
            ingest_dry_run=False,
            verify_only=True,
            run_smoke=run_smoke,
            run_dossier_smoke=run_dossier_smoke,
            run_search_smoke=run_search_smoke,
            search_project=search_project,
            search_location=search_location,
            search_data_store_id=search_data_store_id,
            search_serving_config_id=search_serving_config_id,
            search_query=search_query,
            search_page_size=search_page_size,
            report_dir=report_dir,
            force=force,
            log_level=log_level,
            smoke_api_url=smoke_api_url,
            smoke_token=smoke_token,
            smoke_job=smoke_job,
            smoke_container=smoke_container,
            local_execution=False,
            limit=0,
            rate_limit_delay=0.0,
            timeout="3600s",
        )
    )


@dev_app.command("smoke", help="Run dev smoke only (no bootstrap jobs).")
def bootstrap_dev_smoke(
    project: str = typer.Option(DEFAULT_PROJECT, "--project", help="Target GCP project (default: i4g-dev)."),
    region: str = typer.Option(DEFAULT_REGION, "--region", help="Cloud Run region (default: us-central1)."),
    smoke_api_url: str = typer.Option(
        os.getenv("I4G_SMOKE_API_URL", DEFAULT_SMOKE_API_URL),
        "--smoke-api-url",
        help="API base URL for smoke.",
    ),
    smoke_token: str = typer.Option(
        os.getenv("I4G_SMOKE_TOKEN", "dev-analyst-token"), "--smoke-token", help="API token for smoke."
    ),
    smoke_job: str = typer.Option(
        os.getenv("I4G_SMOKE_JOB", "process-intakes"), "--smoke-job", help="Cloud Run job to execute for smoke."
    ),
    smoke_container: str = typer.Option(
        os.getenv("I4G_SMOKE_CONTAINER", "container-0"), "--smoke-container", help="Container for smoke job."
    ),
    report_dir: Path = typer.Option(
        DEFAULT_REPORT_DIR, "--report-dir", help="Directory to write JSON/Markdown reports."
    ),
    force: bool = typer.Option(False, "--force", help="Allow targeting non-dev projects (never prod)."),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging verbosity (DEBUG/INFO/WARNING/ERROR)."),
) -> None:
    """Run only Cloud Run smoke checks without bootstrapping jobs."""

    _exit_from_return(
        run_dev(
            project=project,
            region=region,
            bundle_uri=None,
            dataset=None,
            wif_service_account=DEFAULT_WIF_SA,
            vertex_job="",
            sql_job="",
            bigquery_job="",
            gcs_assets_job="",
            reports_job="",
            saved_searches_job="",
            seed_reviews_job="",
            skip_vertex=True,
            skip_sql=True,
            skip_bigquery=True,
            skip_gcs_assets=True,
            skip_reports=True,
            skip_saved_searches=True,
            skip_seed_reviews=True,
            skip_ocr=True,
            dry_run=False,
            ingest_dry_run=False,
            verify_only=True,
            run_smoke=True,
            run_dossier_smoke=False,
            run_search_smoke=False,
            search_project=None,
            search_location=None,
            search_data_store_id=None,
            search_serving_config_id=None,
            search_query="wallet address verification",
            search_page_size=5,
            report_dir=report_dir,
            force=force,
            log_level=log_level,
            smoke_api_url=smoke_api_url,
            smoke_token=smoke_token,
            smoke_job=smoke_job,
            smoke_container=smoke_container,
        )
    )


__all__ = ["dev_app"]
