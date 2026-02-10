"""Orchestration logic for dev bootstrap: parse_args, bootstrap_dev, run_dev, main."""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional, Sequence

from i4g.cli.bootstrap.common import (
    DossierSmokeResult,
    SearchSmokeResult,
    SmokeResult,
    run_dossier_smoke,
    run_search_smoke,
)

from .constants import (
    DEFAULT_JOBS,
    DEFAULT_PROJECT,
    DEFAULT_REGION,
    DEFAULT_REPORT_DIR,
    DEFAULT_WIF_SA,
    JobResult,
)
from .ingest import run_local_ingest
from .jobs import build_job_specs, execute_job
from .reports import write_reports
from .smoke import run_smoke
from .utils import configure_logging, format_command, guard_environment, summarize_bundle


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap the dev environment via Cloud Run jobs")
    parser.add_argument("--project", default=DEFAULT_PROJECT, help="Target GCP project (default: i4g-dev).")
    parser.add_argument("--region", default=DEFAULT_REGION, help="Cloud Run region (default: us-central1).")
    parser.add_argument("--bundle", help="Name of a specific bundle to process (e.g. 'ocr_test_images').")
    parser.add_argument("--bundle-uri", dest="bundle_uri", help="Bundle URI passed to all jobs, if supported.")
    parser.add_argument("--dataset", help="Dataset identifier injected into job args, if supported.")
    parser.add_argument(
        "--wif-service-account",
        default=DEFAULT_WIF_SA,
        help="Service account to impersonate via WIF (default: sa-infra@i4g-dev).",
    )
    parser.add_argument("--ingest-job", default=DEFAULT_JOBS["ingest"], help="Ingestion job name.")
    parser.add_argument("--vertex-job", default=DEFAULT_JOBS["vertex"], help="Vertex import job name.")
    parser.add_argument("--sql-job", default=DEFAULT_JOBS["sql"], help="Cloud SQL sync job name.")
    parser.add_argument("--bigquery-job", default=DEFAULT_JOBS["bigquery"], help="BigQuery refresh job name.")
    parser.add_argument("--gcs-assets-job", default=DEFAULT_JOBS["gcs_assets"], help="GCS asset sync job name.")
    parser.add_argument("--reports-job", default=DEFAULT_JOBS["reports"], help="Reports/dossiers job name.")
    parser.add_argument(
        "--saved-searches-job",
        default=DEFAULT_JOBS["saved_searches"],
        help="Saved searches/tag presets job name.",
    )
    parser.add_argument(
        "--seed-reviews-job",
        default=DEFAULT_JOBS["seed_reviews"],
        help="Job to run for seeding reviews (reuses report-job image).",
    )
    parser.add_argument("--skip-seed-reviews", action="store_true", help="Skip seeding reviews.")
    parser.add_argument("--skip-ingest", action="store_true", help="Skip ingestion job.")
    parser.add_argument("--skip-ocr", action="store_true", help="Skip OCR test images bundle.")
    parser.add_argument("--skip-vertex", action="store_true", help="Skip Vertex import job.")
    parser.add_argument("--skip-sql", action="store_true", help="Skip Cloud SQL sync job.")
    parser.add_argument("--skip-bigquery", action="store_true", help="Skip BigQuery refresh job.")
    parser.add_argument("--skip-gcs-assets", action="store_true", help="Skip GCS asset sync job.")
    parser.add_argument("--skip-reports", action="store_true", help="Skip reports/dossiers job.")
    parser.add_argument("--skip-saved-searches", action="store_true", help="Skip saved searches job.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned commands without executing them.")
    parser.add_argument(
        "--ingest-dry-run",
        action="store_true",
        help="Run ingestion in dry-run mode (perform extraction but skip DB writes).",
    )
    parser.add_argument(
        "--verify-only", action="store_true", help="Skip job execution and only run verification smokes."
    )
    parser.add_argument(
        "--run-smoke",
        action="store_true",
        help="Run Cloud Run intake smoke after job execution (or standalone with --verify-only).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit the number of records to ingest (0 = unlimited). Useful for quick smoke tests.",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=DEFAULT_REPORT_DIR,
        help="Directory to write JSON/Markdown reports (default: data/reports/bootstrap_dev).",
    )
    parser.add_argument("--force", action="store_true", help="Allow targeting non-dev projects (never use for prod).")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO).",
    )
    parser.add_argument(
        "--smoke-api-url",
        default=os.getenv("I4G_SMOKE_API_URL", "https://fastapi-gateway-y5jge5w2cq-uc.a.run.app"),
        help="API base URL for smoke (default: dev gateway).",
    )
    parser.add_argument(
        "--smoke-token",
        default=os.getenv("I4G_SMOKE_TOKEN", "dev-analyst-token"),
        help="API token for smoke requests.",
    )
    parser.add_argument(
        "--smoke-job",
        default=os.getenv("I4G_SMOKE_JOB", "process-intakes"),
        help="Cloud Run job to execute for intake smoke.",
    )
    parser.add_argument(
        "--smoke-container",
        default=os.getenv("I4G_SMOKE_CONTAINER", "container-0"),
        help="Container name for the smoke job.",
    )
    parser.add_argument(
        "--local-execution",
        action="store_true",
        help="Run ingestion logic locally instead of triggering Cloud Run jobs.",
    )
    parser.add_argument(
        "--rate-limit-delay",
        type=float,
        default=0.0,
        help="Delay in seconds between records during ingestion (for rate limiting).",
    )
    parser.add_argument(
        "--timeout",
        default="3600s",
        help="Job execution timeout (e.g. 3600s, 60m). Default: 3600s.",
    )
    parser.add_argument("--run-dossier-smoke", action="store_true", help="Run dossier verification smoke via API.")
    parser.add_argument("--run-search-smoke", action="store_true", help="Run Vertex search smoke after bootstrap.")
    parser.add_argument("--search-project", help="Vertex project for search smoke (defaults to --project).")
    parser.add_argument(
        "--search-location", default="global", help="Vertex location for search smoke (default: global)."
    )
    parser.add_argument("--search-data-store-id", help="Vertex data store id for search smoke.")
    parser.add_argument(
        "--search-serving-config-id",
        default="default_search",
        help="Vertex serving config id for search smoke (default: default_search).",
    )
    parser.add_argument(
        "--search-query",
        default="wallet address verification",
        help="Query string to issue during search smoke.",
    )
    parser.add_argument("--search-page-size", type=int, default=5, help="Page size for search smoke results.")
    return parser.parse_args(argv)


def bootstrap_dev(args: argparse.Namespace) -> int:
    configure_logging(args.log_level)
    guard_environment(args.project, args.force)

    if not args.search_project:
        args.search_project = args.project
    if not args.search_location:
        args.search_location = "global"

    bundle_uri_display, bundle_sha = summarize_bundle(args.bundle_uri)
    if bundle_uri_display:
        logging.info("Bundle URI: %s", bundle_uri_display)
    if bundle_sha:
        logging.info("Bundle sha256: %s", bundle_sha)

    logging.info(
        "Bootstrap dev: project=%s region=%s bundle=%s bundle_uri=%s "
        "dataset=%s dry_run=%s verify_only=%s run_smoke=%s local_execution=%s",
        args.project,
        args.region,
        args.bundle or "<none>",
        args.bundle_uri or "<none>",
        args.dataset or "<none>",
        args.dry_run,
        args.verify_only,
        args.run_smoke,
        args.local_execution,
    )

    if args.local_execution and not args.verify_only:
        results = run_local_ingest(args)
    else:
        specs = build_job_specs(args)
        if not specs and not args.verify_only:
            logging.warning("No jobs selected; nothing to do.")
            return 0

        results: list[JobResult] = []
        if not args.verify_only:
            for spec in specs:
                try:
                    results.append(execute_job(spec, args))
                except subprocess.CalledProcessError as exc:
                    results.append(
                        JobResult(
                            label=spec.label,
                            job_name=spec.job_name,
                            command=format_command(
                                ["gcloud", "run", "jobs", "execute", spec.job_name],
                                redacted_flags={"--impersonate-service-account"},
                            ),
                            status="failed",
                            stdout=exc.stdout or "",
                            stderr=exc.stderr or "",
                            error=str(exc),
                        )
                    )
                    write_reports(results, None, None, None, args)
                    return 1
        else:
            logging.info("verify-only set; skipping job execution.")

    smoke_result: SmokeResult | None = None
    if args.run_smoke:
        logging.info("Running Cloud Run smoke...")
        smoke_result = run_smoke(
            project=args.project,
            region=args.region,
            wif_service_account=args.wif_service_account,
            smoke_api_url=args.smoke_api_url,
            smoke_token=args.smoke_token,
            smoke_job=args.smoke_job,
            smoke_container=args.smoke_container,
        )
        if smoke_result.status != "success":
            write_reports(results, smoke_result, None, None, args)
            logging.error("Smoke failed: %s", smoke_result.message)
            return 1

    dossier_smoke: DossierSmokeResult | None = None
    if args.run_dossier_smoke:
        logging.info("Running dossier smoke...")
        dossier_smoke = run_dossier_smoke(
            run_dossier_smoke=True,
            smoke_api_url=args.smoke_api_url,
            smoke_token=args.smoke_token,
        )
        if dossier_smoke.status == "failed":
            write_reports(results, smoke_result, dossier_smoke, None, args)
            logging.error("Dossier smoke failed: %s", dossier_smoke.message)
            return 1

    search_smoke: SearchSmokeResult | None = None
    if args.run_search_smoke:
        logging.info("Running search smoke...")
        search_smoke = run_search_smoke(
            run_search_smoke=True,
            search_project=args.search_project,
            search_location=args.search_location,
            search_data_store_id=args.search_data_store_id,
            search_serving_config_id=args.search_serving_config_id,
            search_query=args.search_query,
            search_page_size=args.search_page_size,
        )
        if search_smoke.status == "failed":
            write_reports(results, smoke_result, dossier_smoke, search_smoke, args)
            logging.error("Search smoke failed: %s", search_smoke.message)
            return 1

    write_reports(results, smoke_result, dossier_smoke, search_smoke, args)
    logging.info("Dev bootstrap completed.")
    return 0


def run_dev(
    *,
    project: str,
    region: str,
    bundle: Optional[str] = None,
    bundle_uri: Optional[str],
    dataset: Optional[str],
    wif_service_account: str,
    ingest_job: str = DEFAULT_JOBS["ingest"],
    vertex_job: str,
    sql_job: str,
    bigquery_job: str,
    gcs_assets_job: str,
    reports_job: str,
    saved_searches_job: str,
    seed_reviews_job: str,
    skip_ingest: bool = False,
    skip_vertex: bool,
    skip_sql: bool,
    skip_bigquery: bool,
    skip_gcs_assets: bool,
    skip_reports: bool,
    skip_saved_searches: bool,
    skip_seed_reviews: bool,
    skip_ocr: bool,
    dry_run: bool,
    ingest_dry_run: bool,
    verify_only: bool,
    run_smoke: bool,
    run_dossier_smoke: bool,
    run_search_smoke: bool,
    search_project: Optional[str],
    search_location: Optional[str],
    search_data_store_id: Optional[str],
    search_serving_config_id: Optional[str],
    search_query: str,
    search_page_size: int,
    report_dir: Path,
    force: bool,
    log_level: str,
    smoke_api_url: str,
    smoke_token: str,
    smoke_job: str,
    smoke_container: str,
    local_execution: bool = False,
    limit: int = 0,
    rate_limit_delay: float = 0.0,
    timeout: str = "3600s",
) -> int:
    args = argparse.Namespace(
        project=project,
        region=region,
        bundle=bundle,
        bundle_uri=bundle_uri,
        dataset=dataset,
        limit=limit,
        rate_limit_delay=rate_limit_delay,
        timeout=timeout,
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
    )
    return bootstrap_dev(args)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    return run_dev(
        project=args.project,
        region=args.region,
        bundle=args.bundle,
        bundle_uri=args.bundle_uri,
        dataset=args.dataset,
        wif_service_account=args.wif_service_account,
        vertex_job=args.vertex_job,
        sql_job=args.sql_job,
        bigquery_job=args.bigquery_job,
        gcs_assets_job=args.gcs_assets_job,
        reports_job=args.reports_job,
        saved_searches_job=args.saved_searches_job,
        skip_vertex=args.skip_vertex,
        skip_sql=args.skip_sql,
        skip_bigquery=args.skip_bigquery,
        skip_gcs_assets=args.skip_gcs_assets,
        skip_reports=args.skip_reports,
        skip_saved_searches=args.skip_saved_searches,
        skip_seed_reviews=args.skip_seed_reviews,
        skip_ocr=args.skip_ocr,
        dry_run=args.dry_run,
        ingest_dry_run=args.ingest_dry_run,
        verify_only=args.verify_only,
        run_smoke=args.run_smoke,
        run_dossier_smoke=args.run_dossier_smoke,
        run_search_smoke=args.run_search_smoke,
        search_project=args.search_project,
        search_location=args.search_location,
        search_data_store_id=args.search_data_store_id,
        search_serving_config_id=args.search_serving_config_id,
        search_query=args.search_query,
        search_page_size=args.search_page_size,
        report_dir=args.report_dir,
        force=args.force,
        log_level=args.log_level,
        smoke_api_url=args.smoke_api_url,
        smoke_token=args.smoke_token,
        smoke_job=args.smoke_job,
        smoke_container=args.smoke_container,
        local_execution=args.local_execution,
        limit=args.limit,
        rate_limit_delay=args.rate_limit_delay,
        timeout=args.timeout,
    )
