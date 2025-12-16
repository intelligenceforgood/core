"""Unified CLI entry point for Intelligence for Good.

Config precedence: settings.default.toml -> settings.local.toml -> env vars (I4G_* with double underscores for nesting) -> CLI flags.
Use ``--install-completion`` to enable shell tab completion (bash required; zsh/fish supported when available).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import typer

from i4g.cli import (
    azure,
    bundle_manifest,
    bundle_storage,
    datasets,
    dossiers,
    extract_tasks,
    indexing,
    ingest,
    pilot,
    reports_tasks,
    saved_searches,
    search,
    smoke,
    synthetic_coverage,
)
from i4g.settings import get_settings

VERSION = (Path(__file__).resolve().parents[3] / "VERSION.txt").read_text().strip()

APP_HELP = (
    "i4g command line for developers and operators. "
    "Config precedence: settings.default.toml -> settings.local.toml -> env vars (I4G_* with __) -> CLI flags. "
    "Use --install-completion to enable shell tab completion. "
    "Guardrails: bootstrap commands enforce I4G_ENV and require --force to target non-local/dev projects."
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

app = typer.Typer(add_completion=True, help=APP_HELP)
bootstrap_app = typer.Typer(help="Bootstrap or reset environments (local sandbox, dev refresh).")
bootstrap_local_app = typer.Typer(help="Local sandbox bootstrap helpers.")
bootstrap_dev_app = typer.Typer(help="Dev bootstrap via Cloud Run jobs.")
env_app = typer.Typer(help="Bootstrap or reset environments (local sandbox, dev refresh).")
settings_app = typer.Typer(help="Inspect and export configuration manifests.")
smoke_app = typer.Typer(help="Run smoketests against local or remote services.")
jobs_app = typer.Typer(help="Invoke background jobs (ingest, report, intake, dossier, account).")
ingest_app = typer.Typer(help="Ingestion utilities and helpers.")
search_app = typer.Typer(help="Search/retrieval queries and evaluations.")
data_app = typer.Typer(help="Dataset preparation and indexing helpers.")
reports_app = typer.Typer(help="Report/dossier verification helpers.")
extract_app = typer.Typer(help="OCR and extraction pipelines.")
admin_app = typer.Typer(help="Saved search and dossier administration.")

app.add_typer(env_app, name="env")
app.add_typer(bootstrap_app, name="bootstrap")
app.add_typer(settings_app, name="settings")
app.add_typer(smoke_app, name="smoke")
app.add_typer(jobs_app, name="jobs")
app.add_typer(ingest_app, name="ingest")
app.add_typer(search_app, name="search")
app.add_typer(data_app, name="data")
app.add_typer(reports_app, name="reports")
app.add_typer(extract_app, name="extract")
app.add_typer(admin_app, name="admin")
app.add_typer(azure.app, name="azure")
bootstrap_app.add_typer(bootstrap_local_app, name="local")
bootstrap_app.add_typer(bootstrap_dev_app, name="dev")


def _exit_from_return(code: int | None) -> None:
    """Honor integer return codes from invoked helpers."""

    if isinstance(code, int) and code != 0:
        raise typer.Exit(code)


def _deprecated_env_notice(new_cmd: str) -> None:
    typer.echo(f"[deprecated] use 'i4g bootstrap {new_cmd}' instead.", err=True)


def _run_bootstrap_local(
    *,
    reset: bool,
    skip_ocr: bool,
    skip_vector: bool,
    bundle_uri: Optional[str],
    dry_run: bool,
    verify_only: bool,
    report_dir: Path,
    smoke_search: bool,
    search_project: Optional[str],
    search_location: Optional[str],
    search_data_store_id: Optional[str],
    search_serving_config_id: str,
    search_query: str,
    search_page_size: int,
    smoke_dossiers: bool,
    smoke_api_url: Optional[str],
    smoke_token: Optional[str],
    smoke_dossier_status: str,
    smoke_dossier_limit: int,
    smoke_dossier_plan_id: Optional[str],
    force: bool,
) -> None:
    from scripts import bootstrap_local_sandbox

    argv: list[str] = []
    if reset:
        argv.append("--reset")
    if skip_ocr:
        argv.append("--skip-ocr")
    if skip_vector:
        argv.append("--skip-vector")
    if bundle_uri:
        argv.extend(["--bundle-uri", bundle_uri])
    if dry_run:
        argv.append("--dry-run")
    if verify_only:
        argv.append("--verify-only")
    if report_dir:
        argv.extend(["--report-dir", str(report_dir)])
    if smoke_search:
        argv.append("--smoke-search")
    if search_project:
        argv.extend(["--search-project", search_project])
    if search_location:
        argv.extend(["--search-location", search_location])
    if search_data_store_id:
        argv.extend(["--search-data-store-id", search_data_store_id])
    if search_serving_config_id:
        argv.extend(["--search-serving-config-id", search_serving_config_id])
    if search_query:
        argv.extend(["--search-query", search_query])
    if search_page_size:
        argv.extend(["--search-page-size", str(search_page_size)])
    if smoke_dossiers:
        argv.append("--smoke-dossiers")
    if smoke_api_url:
        argv.extend(["--smoke-api-url", smoke_api_url])
    if smoke_token:
        argv.extend(["--smoke-token", smoke_token])
    if smoke_dossier_status:
        argv.extend(["--smoke-dossier-status", smoke_dossier_status])
    if smoke_dossier_limit:
        argv.extend(["--smoke-dossier-limit", str(smoke_dossier_limit)])
    if smoke_dossier_plan_id:
        argv.extend(["--smoke-dossier-plan-id", smoke_dossier_plan_id])
    if force:
        argv.append("--force")
    bootstrap_local_sandbox.main(argv)


def _run_bootstrap_dev(
    *,
    project: str,
    region: str,
    bundle_uri: Optional[str],
    dataset: Optional[str],
    wif_service_account: str,
    firestore_job: str,
    vertex_job: str,
    sql_job: str,
    bigquery_job: str,
    gcs_assets_job: str,
    reports_job: str,
    saved_searches_job: str,
    skip_firestore: bool,
    skip_vertex: bool,
    skip_sql: bool,
    skip_bigquery: bool,
    skip_gcs_assets: bool,
    skip_reports: bool,
    skip_saved_searches: bool,
    dry_run: bool,
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
) -> None:
    from scripts import bootstrap_dev_env

    argv: list[str] = [
        "--project",
        project,
        "--region",
        region,
        "--wif-service-account",
        wif_service_account,
        "--firestore-job",
        firestore_job,
        "--vertex-job",
        vertex_job,
        "--sql-job",
        sql_job,
        "--bigquery-job",
        bigquery_job,
        "--gcs-assets-job",
        gcs_assets_job,
        "--reports-job",
        reports_job,
        "--saved-searches-job",
        saved_searches_job,
        "--report-dir",
        str(report_dir),
        "--log-level",
        log_level,
        "--smoke-api-url",
        smoke_api_url,
        "--smoke-token",
        smoke_token,
        "--smoke-job",
        smoke_job,
        "--smoke-container",
        smoke_container,
    ]
    if bundle_uri:
        argv.extend(["--bundle-uri", bundle_uri])
    if dataset:
        argv.extend(["--dataset", dataset])
    if skip_firestore:
        argv.append("--skip-firestore")
    if skip_vertex:
        argv.append("--skip-vertex")
    if skip_sql:
        argv.append("--skip-sql")
    if skip_bigquery:
        argv.append("--skip-bigquery")
    if skip_gcs_assets:
        argv.append("--skip-gcs-assets")
    if skip_reports:
        argv.append("--skip-reports")
    if skip_saved_searches:
        argv.append("--skip-saved-searches")
    if dry_run:
        argv.append("--dry-run")
    if verify_only:
        argv.append("--verify-only")
    if run_smoke:
        argv.append("--run-smoke")
    if run_dossier_smoke:
        argv.append("--run-dossier-smoke")
    if run_search_smoke:
        argv.append("--run-search-smoke")
    if search_project:
        argv.extend(["--search-project", search_project])
    if search_location:
        argv.extend(["--search-location", search_location])
    if search_data_store_id:
        argv.extend(["--search-data-store-id", search_data_store_id])
    if search_serving_config_id:
        argv.extend(["--search-serving-config-id", search_serving_config_id])
    if search_query:
        argv.extend(["--search-query", search_query])
    if search_page_size:
        argv.extend(["--search-page-size", str(search_page_size)])
    if force:
        argv.append("--force")

    _exit_from_return(bootstrap_dev_env.main(argv))


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context, version: bool = typer.Option(False, "--version", help="Show version and exit.")) -> None:
    """Show help when no subcommand is provided."""

    if version:
        typer.echo(f"i4g {VERSION}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


@bootstrap_local_app.command("reset", help="Wipe and reload local sandbox artifacts.")
def bootstrap_local_reset(
    skip_ocr: bool = typer.Option(False, "--skip-ocr", help="Skip generating chat screenshots and OCR."),
    skip_vector: bool = typer.Option(False, "--skip-vector", help="Skip rebuilding vector/structured stores."),
    bundle_uri: Optional[str] = typer.Option(
        None, "--bundle-uri", help="Optional bundle JSONL path/URI to place into data/bundles."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print planned actions without mutating disk."),
    report_dir: Path = typer.Option(Path("data/reports"), "--report-dir", help="Verification report directory."),
    smoke_search: bool = typer.Option(False, "--smoke-search", help="Run Vertex search smoke after verification."),
    search_project: Optional[str] = typer.Option(
        None, "--search-project", help="Vertex project for search smoke (defaults to settings/env)."
    ),
    search_location: Optional[str] = typer.Option(
        None, "--search-location", help="Vertex location for search smoke (default from settings/env)."
    ),
    search_data_store_id: Optional[str] = typer.Option(
        None, "--search-data-store-id", help="Vertex data store id for search smoke."
    ),
    search_serving_config_id: str = typer.Option(
        "default_search", "--search-serving-config-id", help="Vertex serving config id for search smoke."
    ),
    search_query: str = typer.Option("wallet address verification", "--search-query", help="Search smoke query."),
    search_page_size: int = typer.Option(5, "--search-page-size", help="Search smoke page size."),
    smoke_dossiers: bool = typer.Option(False, "--smoke-dossiers", help="Run dossier verification smoke."),
    smoke_api_url: Optional[str] = typer.Option(
        None, "--smoke-api-url", help="API base URL for dossier smoke (defaults to env or localhost)."
    ),
    smoke_token: Optional[str] = typer.Option(None, "--smoke-token", help="API token for dossier smoke."),
    smoke_dossier_status: str = typer.Option(
        "completed", "--smoke-dossier-status", help="Queue status filter for dossier smoke."
    ),
    smoke_dossier_limit: int = typer.Option(5, "--smoke-dossier-limit", help="Maximum dossiers to inspect."),
    smoke_dossier_plan_id: Optional[str] = typer.Option(
        None, "--smoke-dossier-plan-id", help="Specific dossier plan_id to verify during smoke."
    ),
    force: bool = typer.Option(False, "--force", help="Allow running when I4G_ENV is not local."),
) -> None:
    """Reset local sandbox then reload sample data."""

    _run_bootstrap_local(
        reset=True,
        skip_ocr=skip_ocr,
        skip_vector=skip_vector,
        bundle_uri=bundle_uri,
        dry_run=dry_run,
        verify_only=False,
        report_dir=report_dir,
        smoke_search=smoke_search,
        search_project=search_project,
        search_location=search_location,
        search_data_store_id=search_data_store_id,
        search_serving_config_id=search_serving_config_id,
        search_query=search_query,
        search_page_size=search_page_size,
        smoke_dossiers=smoke_dossiers,
        smoke_api_url=smoke_api_url,
        smoke_token=smoke_token,
        smoke_dossier_status=smoke_dossier_status,
        smoke_dossier_limit=smoke_dossier_limit,
        smoke_dossier_plan_id=smoke_dossier_plan_id,
        force=force,
    )


@bootstrap_local_app.command("load", help="Refresh local sandbox without wiping artifacts.")
def bootstrap_local_load(
    skip_ocr: bool = typer.Option(False, "--skip-ocr", help="Skip generating chat screenshots and OCR."),
    skip_vector: bool = typer.Option(False, "--skip-vector", help="Skip rebuilding vector/structured stores."),
    bundle_uri: Optional[str] = typer.Option(
        None, "--bundle-uri", help="Optional bundle JSONL path/URI to place into data/bundles."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print planned actions without mutating disk."),
    report_dir: Path = typer.Option(Path("data/reports"), "--report-dir", help="Verification report directory."),
    smoke_search: bool = typer.Option(False, "--smoke-search", help="Run Vertex search smoke after verification."),
    search_project: Optional[str] = typer.Option(
        None, "--search-project", help="Vertex project for search smoke (defaults to settings/env)."
    ),
    search_location: Optional[str] = typer.Option(
        None, "--search-location", help="Vertex location for search smoke (default from settings/env)."
    ),
    search_data_store_id: Optional[str] = typer.Option(
        None, "--search-data-store-id", help="Vertex data store id for search smoke."
    ),
    search_serving_config_id: str = typer.Option(
        "default_search", "--search-serving-config-id", help="Vertex serving config id for search smoke."
    ),
    search_query: str = typer.Option("wallet address verification", "--search-query", help="Search smoke query."),
    search_page_size: int = typer.Option(5, "--search-page-size", help="Search smoke page size."),
    smoke_dossiers: bool = typer.Option(False, "--smoke-dossiers", help="Run dossier verification smoke."),
    smoke_api_url: Optional[str] = typer.Option(
        None, "--smoke-api-url", help="API base URL for dossier smoke (defaults to env or localhost)."
    ),
    smoke_token: Optional[str] = typer.Option(None, "--smoke-token", help="API token for dossier smoke."),
    smoke_dossier_status: str = typer.Option(
        "completed", "--smoke-dossier-status", help="Queue status filter for dossier smoke."
    ),
    smoke_dossier_limit: int = typer.Option(5, "--smoke-dossier-limit", help="Maximum dossiers to inspect."),
    smoke_dossier_plan_id: Optional[str] = typer.Option(
        None, "--smoke-dossier-plan-id", help="Specific dossier plan_id to verify during smoke."
    ),
    force: bool = typer.Option(False, "--force", help="Allow running when I4G_ENV is not local."),
) -> None:
    """Refresh local sandbox data without a reset."""

    _run_bootstrap_local(
        reset=False,
        skip_ocr=skip_ocr,
        skip_vector=skip_vector,
        bundle_uri=bundle_uri,
        dry_run=dry_run,
        verify_only=False,
        report_dir=report_dir,
        smoke_search=smoke_search,
        search_project=search_project,
        search_location=search_location,
        search_data_store_id=search_data_store_id,
        search_serving_config_id=search_serving_config_id,
        search_query=search_query,
        search_page_size=search_page_size,
        smoke_dossiers=smoke_dossiers,
        smoke_api_url=smoke_api_url,
        smoke_token=smoke_token,
        smoke_dossier_status=smoke_dossier_status,
        smoke_dossier_limit=smoke_dossier_limit,
        smoke_dossier_plan_id=smoke_dossier_plan_id,
        force=force,
    )


@bootstrap_local_app.command("verify", help="Run verification only for the local sandbox.")
def bootstrap_local_verify(
    bundle_uri: Optional[str] = typer.Option(
        None, "--bundle-uri", help="Optional bundle JSONL path/URI to place into data/bundles."
    ),
    report_dir: Path = typer.Option(Path("data/reports"), "--report-dir", help="Verification report directory."),
    smoke_search: bool = typer.Option(False, "--smoke-search", help="Run Vertex search smoke after verification."),
    search_project: Optional[str] = typer.Option(
        None, "--search-project", help="Vertex project for search smoke (defaults to settings/env)."
    ),
    search_location: Optional[str] = typer.Option(
        None, "--search-location", help="Vertex location for search smoke (default from settings/env)."
    ),
    search_data_store_id: Optional[str] = typer.Option(
        None, "--search-data-store-id", help="Vertex data store id for search smoke."
    ),
    search_serving_config_id: str = typer.Option(
        "default_search", "--search-serving-config-id", help="Vertex serving config id for search smoke."
    ),
    search_query: str = typer.Option("wallet address verification", "--search-query", help="Search smoke query."),
    search_page_size: int = typer.Option(5, "--search-page-size", help="Search smoke page size."),
    smoke_dossiers: bool = typer.Option(False, "--smoke-dossiers", help="Run dossier verification smoke."),
    smoke_api_url: Optional[str] = typer.Option(
        None, "--smoke-api-url", help="API base URL for dossier smoke (defaults to env or localhost)."
    ),
    smoke_token: Optional[str] = typer.Option(None, "--smoke-token", help="API token for dossier smoke."),
    smoke_dossier_status: str = typer.Option(
        "completed", "--smoke-dossier-status", help="Queue status filter for dossier smoke."
    ),
    smoke_dossier_limit: int = typer.Option(5, "--smoke-dossier-limit", help="Maximum dossiers to inspect."),
    smoke_dossier_plan_id: Optional[str] = typer.Option(
        None, "--smoke-dossier-plan-id", help="Specific dossier plan_id to verify during smoke."
    ),
    force: bool = typer.Option(False, "--force", help="Allow running when I4G_ENV is not local."),
) -> None:
    """Emit local verification reports without regenerating data."""

    _run_bootstrap_local(
        reset=False,
        skip_ocr=False,
        skip_vector=False,
        bundle_uri=bundle_uri,
        dry_run=False,
        verify_only=True,
        report_dir=report_dir,
        smoke_search=smoke_search,
        search_project=search_project,
        search_location=search_location,
        search_data_store_id=search_data_store_id,
        search_serving_config_id=search_serving_config_id,
        search_query=search_query,
        search_page_size=search_page_size,
        smoke_dossiers=smoke_dossiers,
        smoke_api_url=smoke_api_url,
        smoke_token=smoke_token,
        smoke_dossier_status=smoke_dossier_status,
        smoke_dossier_limit=smoke_dossier_limit,
        smoke_dossier_plan_id=smoke_dossier_plan_id,
        force=force,
    )


@bootstrap_local_app.command("smoke", help="Alias for local verification-only checks.")
def bootstrap_local_smoke(
    bundle_uri: Optional[str] = typer.Option(
        None, "--bundle-uri", help="Optional bundle JSONL path/URI to place into data/bundles."
    ),
    report_dir: Path = typer.Option(Path("data/reports"), "--report-dir", help="Verification report directory."),
    smoke_search: bool = typer.Option(False, "--smoke-search", help="Run Vertex search smoke after verification."),
    smoke_dossiers: bool = typer.Option(False, "--smoke-dossiers", help="Run dossier verification smoke."),
    smoke_api_url: Optional[str] = typer.Option(
        None, "--smoke-api-url", help="API base URL for dossier smoke (defaults to env or localhost)."
    ),
    smoke_token: Optional[str] = typer.Option(None, "--smoke-token", help="API token for dossier smoke."),
    smoke_dossier_status: str = typer.Option(
        "completed", "--smoke-dossier-status", help="Queue status filter for dossier smoke."
    ),
    smoke_dossier_limit: int = typer.Option(5, "--smoke-dossier-limit", help="Maximum dossiers to inspect."),
    smoke_dossier_plan_id: Optional[str] = typer.Option(
        None, "--smoke-dossier-plan-id", help="Specific dossier plan_id to verify during smoke."
    ),
    force: bool = typer.Option(False, "--force", help="Allow running when I4G_ENV is not local."),
) -> None:
    """Run local verification-only checks (smoke alias)."""

    _run_bootstrap_local(
        reset=False,
        skip_ocr=False,
        skip_vector=False,
        bundle_uri=bundle_uri,
        dry_run=False,
        verify_only=True,
        report_dir=report_dir,
        smoke_search=smoke_search,
        search_project=None,
        search_location=None,
        search_data_store_id=None,
        search_serving_config_id="default_search",
        search_query="wallet address verification",
        search_page_size=5,
        smoke_dossiers=smoke_dossiers,
        smoke_api_url=smoke_api_url,
        smoke_token=smoke_token,
        smoke_dossier_status=smoke_dossier_status,
        smoke_dossier_limit=smoke_dossier_limit,
        smoke_dossier_plan_id=smoke_dossier_plan_id,
        force=force,
    )


@bootstrap_app.command("seed-sample", help="Enqueue the sample dossier plan into the local queue store.")
def bootstrap_seed_sample() -> None:
    from scripts import enqueue_sample_dossier

    _exit_from_return(enqueue_sample_dossier.main())


@bootstrap_dev_app.command("reset", help="Run dev bootstrap jobs (Cloud Run) with optional smoke.")
def bootstrap_dev_reset(
    project: str = typer.Option("i4g-dev", "--project", help="Target GCP project (default: i4g-dev)."),
    region: str = typer.Option("us-central1", "--region", help="Cloud Run region (default: us-central1)."),
    bundle_uri: Optional[str] = typer.Option(None, "--bundle-uri", help="Bundle URI passed to jobs, if supported."),
    dataset: Optional[str] = typer.Option(None, "--dataset", help="Dataset identifier injected into job args."),
    wif_service_account: str = typer.Option(
        "sa-infra@i4g-dev.iam.gserviceaccount.com",
        "--wif-service-account",
        help="Service account to impersonate via WIF.",
    ),
    firestore_job: str = typer.Option("bootstrap-firestore", "--firestore-job", help="Firestore refresh job."),
    vertex_job: str = typer.Option("bootstrap-vertex", "--vertex-job", help="Vertex import job."),
    sql_job: str = typer.Option("bootstrap-sql", "--sql-job", help="SQL/Firestore sync job."),
    bigquery_job: str = typer.Option("bootstrap-bigquery", "--bigquery-job", help="BigQuery refresh job."),
    gcs_assets_job: str = typer.Option("bootstrap-gcs-assets", "--gcs-assets-job", help="GCS asset sync job."),
    reports_job: str = typer.Option("bootstrap-reports", "--reports-job", help="Reports/dossiers job."),
    saved_searches_job: str = typer.Option(
        "bootstrap-saved-searches", "--saved-searches-job", help="Saved searches/tag presets job."
    ),
    skip_firestore: bool = typer.Option(False, "--skip-firestore", help="Skip Firestore refresh job."),
    skip_vertex: bool = typer.Option(False, "--skip-vertex", help="Skip Vertex import job."),
    skip_sql: bool = typer.Option(False, "--skip-sql", help="Skip SQL/Firestore sync job."),
    skip_bigquery: bool = typer.Option(False, "--skip-bigquery", help="Skip BigQuery refresh job."),
    skip_gcs_assets: bool = typer.Option(False, "--skip-gcs-assets", help="Skip GCS asset sync job."),
    skip_reports: bool = typer.Option(False, "--skip-reports", help="Skip reports/dossiers job."),
    skip_saved_searches: bool = typer.Option(False, "--skip-saved-searches", help="Skip saved searches job."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print planned commands without executing."),
    run_smoke: bool = typer.Option(False, "--run-smoke/--no-run-smoke", help="Run Cloud Run intake smoke."),
    run_dossier_smoke: bool = typer.Option(
        False, "--run-dossier-smoke/--no-run-dossier-smoke", help="Run dossier verification smoke."
    ),
    run_search_smoke: bool = typer.Option(
        False, "--run-search-smoke/--no-run-search-smoke", help="Run Vertex search smoke."
    ),
    search_project: Optional[str] = typer.Option(
        None, "--search-project", help="Vertex project for search smoke (defaults to --project)."
    ),
    search_location: Optional[str] = typer.Option(
        None, "--search-location", help="Vertex location for search smoke (default from orchestrator)."
    ),
    search_data_store_id: Optional[str] = typer.Option(
        None, "--search-data-store-id", help="Vertex data store id for search smoke."
    ),
    search_serving_config_id: str = typer.Option(
        "default_search", "--search-serving-config-id", help="Vertex serving config id for search smoke."
    ),
    search_query: str = typer.Option("wallet address verification", "--search-query", help="Search smoke query."),
    search_page_size: int = typer.Option(5, "--search-page-size", help="Result page size for search smoke."),
    report_dir: Path = typer.Option(
        Path("data/reports/dev_bootstrap"), "--report-dir", help="Directory to write JSON/Markdown reports."
    ),
    force: bool = typer.Option(False, "--force", help="Allow targeting non-dev projects (never prod)."),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging verbosity (DEBUG/INFO/WARNING/ERROR)."),
    smoke_api_url: str = typer.Option(
        "https://fastapi-gateway-y5jge5w2cq-uc.a.run.app", "--smoke-api-url", help="API base URL for smoke."
    ),
    smoke_token: str = typer.Option("dev-analyst-token", "--smoke-token", help="API token for smoke."),
    smoke_job: str = typer.Option("process-intakes", "--smoke-job", help="Cloud Run job to execute for smoke."),
    smoke_container: str = typer.Option("container-0", "--smoke-container", help="Container for smoke job."),
) -> None:
    """Execute dev Cloud Run bootstrap jobs; optional smoke after run."""

    _run_bootstrap_dev(
        project=project,
        region=region,
        bundle_uri=bundle_uri,
        dataset=dataset,
        wif_service_account=wif_service_account,
        firestore_job=firestore_job,
        vertex_job=vertex_job,
        sql_job=sql_job,
        bigquery_job=bigquery_job,
        gcs_assets_job=gcs_assets_job,
        reports_job=reports_job,
        saved_searches_job=saved_searches_job,
        skip_firestore=skip_firestore,
        skip_vertex=skip_vertex,
        skip_sql=skip_sql,
        skip_bigquery=skip_bigquery,
        skip_gcs_assets=skip_gcs_assets,
        skip_reports=skip_reports,
        skip_saved_searches=skip_saved_searches,
        dry_run=dry_run,
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
    )


@bootstrap_dev_app.command("load", help="Alias of reset for dev bootstrap jobs.")
def bootstrap_dev_load(
    project: str = typer.Option("i4g-dev", "--project", help="Target GCP project (default: i4g-dev)."),
    region: str = typer.Option("us-central1", "--region", help="Cloud Run region (default: us-central1)."),
    bundle_uri: Optional[str] = typer.Option(None, "--bundle-uri", help="Bundle URI passed to jobs, if supported."),
    dataset: Optional[str] = typer.Option(None, "--dataset", help="Dataset identifier injected into job args."),
    wif_service_account: str = typer.Option(
        "sa-infra@i4g-dev.iam.gserviceaccount.com",
        "--wif-service-account",
        help="Service account to impersonate via WIF.",
    ),
    firestore_job: str = typer.Option("bootstrap-firestore", "--firestore-job", help="Firestore refresh job."),
    vertex_job: str = typer.Option("bootstrap-vertex", "--vertex-job", help="Vertex import job."),
    sql_job: str = typer.Option("bootstrap-sql", "--sql-job", help="SQL/Firestore sync job."),
    bigquery_job: str = typer.Option("bootstrap-bigquery", "--bigquery-job", help="BigQuery refresh job."),
    gcs_assets_job: str = typer.Option("bootstrap-gcs-assets", "--gcs-assets-job", help="GCS asset sync job."),
    reports_job: str = typer.Option("bootstrap-reports", "--reports-job", help="Reports/dossiers job."),
    saved_searches_job: str = typer.Option(
        "bootstrap-saved-searches", "--saved-searches-job", help="Saved searches/tag presets job."
    ),
    skip_firestore: bool = typer.Option(False, "--skip-firestore", help="Skip Firestore refresh job."),
    skip_vertex: bool = typer.Option(False, "--skip-vertex", help="Skip Vertex import job."),
    skip_sql: bool = typer.Option(False, "--skip-sql", help="Skip SQL/Firestore sync job."),
    skip_bigquery: bool = typer.Option(False, "--skip-bigquery", help="Skip BigQuery refresh job."),
    skip_gcs_assets: bool = typer.Option(False, "--skip-gcs-assets", help="Skip GCS asset sync job."),
    skip_reports: bool = typer.Option(False, "--skip-reports", help="Skip reports/dossiers job."),
    skip_saved_searches: bool = typer.Option(False, "--skip-saved-searches", help="Skip saved searches job."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print planned commands without executing."),
    run_smoke: bool = typer.Option(False, "--run-smoke/--no-run-smoke", help="Run Cloud Run intake smoke."),
    run_dossier_smoke: bool = typer.Option(
        False, "--run-dossier-smoke/--no-run-dossier-smoke", help="Run dossier verification smoke."
    ),
    run_search_smoke: bool = typer.Option(
        False, "--run-search-smoke/--no-run-search-smoke", help="Run Vertex search smoke."
    ),
    search_project: Optional[str] = typer.Option(
        None, "--search-project", help="Vertex project for search smoke (defaults to --project)."
    ),
    search_location: Optional[str] = typer.Option(
        None, "--search-location", help="Vertex location for search smoke (default from orchestrator)."
    ),
    search_data_store_id: Optional[str] = typer.Option(
        None, "--search-data-store-id", help="Vertex data store id for search smoke."
    ),
    search_serving_config_id: str = typer.Option(
        "default_search", "--search-serving-config-id", help="Vertex serving config id for search smoke."
    ),
    search_query: str = typer.Option("wallet address verification", "--search-query", help="Search smoke query."),
    search_page_size: int = typer.Option(5, "--search-page-size", help="Result page size for search smoke."),
    report_dir: Path = typer.Option(
        Path("data/reports/dev_bootstrap"), "--report-dir", help="Directory to write JSON/Markdown reports."
    ),
    force: bool = typer.Option(False, "--force", help="Allow targeting non-dev projects (never prod)."),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging verbosity (DEBUG/INFO/WARNING/ERROR)."),
    smoke_api_url: str = typer.Option(
        "https://fastapi-gateway-y5jge5w2cq-uc.a.run.app", "--smoke-api-url", help="API base URL for smoke."
    ),
    smoke_token: str = typer.Option("dev-analyst-token", "--smoke-token", help="API token for smoke."),
    smoke_job: str = typer.Option("process-intakes", "--smoke-job", help="Cloud Run job to execute for smoke."),
    smoke_container: str = typer.Option("container-0", "--smoke-container", help="Container for smoke job."),
) -> None:
    """Alias of reset for dev bootstrap jobs (kept for symmetry)."""

    _run_bootstrap_dev(
        project=project,
        region=region,
        bundle_uri=bundle_uri,
        dataset=dataset,
        wif_service_account=wif_service_account,
        firestore_job=firestore_job,
        vertex_job=vertex_job,
        sql_job=sql_job,
        bigquery_job=bigquery_job,
        gcs_assets_job=gcs_assets_job,
        reports_job=reports_job,
        saved_searches_job=saved_searches_job,
        skip_firestore=skip_firestore,
        skip_vertex=skip_vertex,
        skip_sql=skip_sql,
        skip_bigquery=skip_bigquery,
        skip_gcs_assets=skip_gcs_assets,
        skip_reports=skip_reports,
        skip_saved_searches=skip_saved_searches,
        dry_run=dry_run,
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
    )


@bootstrap_dev_app.command("verify", help="Run verification-only flow for dev (smoke optional).")
def bootstrap_dev_verify(
    project: str = typer.Option("i4g-dev", "--project", help="Target GCP project (default: i4g-dev)."),
    region: str = typer.Option("us-central1", "--region", help="Cloud Run region (default: us-central1)."),
    bundle_uri: Optional[str] = typer.Option(None, "--bundle-uri", help="Bundle URI passed to jobs, if supported."),
    dataset: Optional[str] = typer.Option(None, "--dataset", help="Dataset identifier injected into job args."),
    wif_service_account: str = typer.Option(
        "sa-infra@i4g-dev.iam.gserviceaccount.com",
        "--wif-service-account",
        help="Service account to impersonate via WIF.",
    ),
    firestore_job: str = typer.Option("bootstrap-firestore", "--firestore-job", help="Firestore refresh job."),
    vertex_job: str = typer.Option("bootstrap-vertex", "--vertex-job", help="Vertex import job."),
    sql_job: str = typer.Option("bootstrap-sql", "--sql-job", help="SQL/Firestore sync job."),
    bigquery_job: str = typer.Option("bootstrap-bigquery", "--bigquery-job", help="BigQuery refresh job."),
    gcs_assets_job: str = typer.Option("bootstrap-gcs-assets", "--gcs-assets-job", help="GCS asset sync job."),
    reports_job: str = typer.Option("bootstrap-reports", "--reports-job", help="Reports/dossiers job."),
    saved_searches_job: str = typer.Option(
        "bootstrap-saved-searches", "--saved-searches-job", help="Saved searches/tag presets job."
    ),
    run_smoke: bool = typer.Option(True, "--run-smoke/--no-run-smoke", help="Run Cloud Run intake smoke."),
    run_dossier_smoke: bool = typer.Option(
        True, "--run-dossier-smoke/--no-run-dossier-smoke", help="Run dossier verification smoke."
    ),
    run_search_smoke: bool = typer.Option(
        True, "--run-search-smoke/--no-run-search-smoke", help="Run Vertex search smoke."
    ),
    search_project: Optional[str] = typer.Option(
        None, "--search-project", help="Vertex project for search smoke (defaults to --project)."
    ),
    search_location: Optional[str] = typer.Option(
        None, "--search-location", help="Vertex location for search smoke (default from orchestrator)."
    ),
    search_data_store_id: Optional[str] = typer.Option(
        None, "--search-data-store-id", help="Vertex data store id for search smoke."
    ),
    search_serving_config_id: str = typer.Option(
        "default_search", "--search-serving-config-id", help="Vertex serving config id for search smoke."
    ),
    search_query: str = typer.Option("wallet address verification", "--search-query", help="Search smoke query."),
    search_page_size: int = typer.Option(5, "--search-page-size", help="Result page size for search smoke."),
    report_dir: Path = typer.Option(
        Path("data/reports/dev_bootstrap"), "--report-dir", help="Directory to write JSON/Markdown reports."
    ),
    force: bool = typer.Option(False, "--force", help="Allow targeting non-dev projects (never prod)."),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging verbosity (DEBUG/INFO/WARNING/ERROR)."),
    smoke_api_url: str = typer.Option(
        "https://fastapi-gateway-y5jge5w2cq-uc.a.run.app", "--smoke-api-url", help="API base URL for smoke."
    ),
    smoke_token: str = typer.Option("dev-analyst-token", "--smoke-token", help="API token for smoke."),
    smoke_job: str = typer.Option("process-intakes", "--smoke-job", help="Cloud Run job to execute for smoke."),
    smoke_container: str = typer.Option("container-0", "--smoke-container", help="Container for smoke job."),
) -> None:
    """Skip job execution and only run verification/smoke for dev."""

    _run_bootstrap_dev(
        project=project,
        region=region,
        bundle_uri=bundle_uri,
        dataset=dataset,
        wif_service_account=wif_service_account,
        firestore_job=firestore_job,
        vertex_job=vertex_job,
        sql_job=sql_job,
        bigquery_job=bigquery_job,
        gcs_assets_job=gcs_assets_job,
        reports_job=reports_job,
        saved_searches_job=saved_searches_job,
        skip_firestore=False,
        skip_vertex=False,
        skip_sql=False,
        skip_bigquery=False,
        skip_gcs_assets=False,
        skip_reports=False,
        skip_saved_searches=False,
        dry_run=False,
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
    )


@bootstrap_dev_app.command("smoke", help="Run dev smoke only (no bootstrap jobs).")
def bootstrap_dev_smoke(
    project: str = typer.Option("i4g-dev", "--project", help="Target GCP project (default: i4g-dev)."),
    region: str = typer.Option("us-central1", "--region", help="Cloud Run region (default: us-central1)."),
    smoke_api_url: str = typer.Option(
        "https://fastapi-gateway-y5jge5w2cq-uc.a.run.app", "--smoke-api-url", help="API base URL for smoke."
    ),
    smoke_token: str = typer.Option("dev-analyst-token", "--smoke-token", help="API token for smoke."),
    smoke_job: str = typer.Option("process-intakes", "--smoke-job", help="Cloud Run job to execute for smoke."),
    smoke_container: str = typer.Option("container-0", "--smoke-container", help="Container for smoke job."),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging verbosity (DEBUG/INFO/WARNING/ERROR)."),
    report_dir: Path = typer.Option(
        Path("data/reports/dev_bootstrap"), "--report-dir", help="Directory to write JSON/Markdown reports."
    ),
    force: bool = typer.Option(False, "--force", help="Allow targeting non-dev projects (never prod)."),
) -> None:
    """Run dev Cloud Run smoke without executing bootstrap jobs."""

    _run_bootstrap_dev(
        project=project,
        region=region,
        bundle_uri=None,
        dataset=None,
        wif_service_account="sa-infra@i4g-dev.iam.gserviceaccount.com",
        firestore_job="",
        vertex_job="",
        sql_job="",
        bigquery_job="",
        gcs_assets_job="",
        reports_job="",
        saved_searches_job="",
        skip_firestore=True,
        skip_vertex=True,
        skip_sql=True,
        skip_bigquery=True,
        skip_gcs_assets=True,
        skip_reports=True,
        skip_saved_searches=True,
        dry_run=False,
        verify_only=True,
        run_smoke=True,
        report_dir=report_dir,
        force=force,
        log_level=log_level,
        smoke_api_url=smoke_api_url,
        smoke_token=smoke_token,
        smoke_job=smoke_job,
        smoke_container=smoke_container,
    )


@env_app.command("bootstrap-local", help="Refresh local sandbox data and artifacts.")
def env_bootstrap_local(
    skip_ocr: bool = typer.Option(False, "--skip-ocr", help="Skip generating chat screenshots and OCR."),
    skip_vector: bool = typer.Option(False, "--skip-vector", help="Skip rebuilding vector/structured stores."),
    reset: bool = typer.Option(False, "--reset", help="Delete derived artifacts before regenerating."),
    bundle_uri: Optional[str] = typer.Option(
        None, "--bundle-uri", help="Optional bundle JSONL path/URI to place into data/bundles."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print planned actions without mutating disk."),
    verify_only: bool = typer.Option(False, "--verify-only", help="Only run verification without regenerating."),
    report_dir: Path = typer.Option(Path("data/reports"), "--report-dir", help="Verification report directory."),
    force: bool = typer.Option(False, "--force", help="Allow running when I4G_ENV is not local."),
) -> None:
    """Run the local sandbox bootstrap pipeline."""

    _deprecated_env_notice("local <reset|load|verify|smoke>")
    _run_bootstrap_local(
        reset=reset,
        skip_ocr=skip_ocr,
        skip_vector=skip_vector,
        bundle_uri=bundle_uri,
        dry_run=dry_run,
        verify_only=verify_only,
        report_dir=report_dir,
        force=force,
    )


@env_app.command("bootstrap-dev", help="Refresh dev environment via Cloud Run jobs.")
def env_bootstrap_dev(
    project: str = typer.Option("i4g-dev", "--project", help="Target GCP project (default: i4g-dev)."),
    region: str = typer.Option("us-central1", "--region", help="Cloud Run region (default: us-central1)."),
    bundle_uri: Optional[str] = typer.Option(None, "--bundle-uri", help="Bundle URI passed to jobs, if supported."),
    dataset: Optional[str] = typer.Option(None, "--dataset", help="Dataset identifier injected into job args."),
    wif_service_account: str = typer.Option(
        "sa-infra@i4g-dev.iam.gserviceaccount.com",
        "--wif-service-account",
        help="Service account to impersonate via WIF.",
    ),
    firestore_job: str = typer.Option("bootstrap-firestore", "--firestore-job", help="Firestore refresh job."),
    vertex_job: str = typer.Option("bootstrap-vertex", "--vertex-job", help="Vertex import job."),
    sql_job: str = typer.Option("bootstrap-sql", "--sql-job", help="SQL/Firestore sync job."),
    bigquery_job: str = typer.Option("bootstrap-bigquery", "--bigquery-job", help="BigQuery refresh job."),
    gcs_assets_job: str = typer.Option("bootstrap-gcs-assets", "--gcs-assets-job", help="GCS asset sync job."),
    reports_job: str = typer.Option("bootstrap-reports", "--reports-job", help="Reports/dossiers job."),
    saved_searches_job: str = typer.Option(
        "bootstrap-saved-searches", "--saved-searches-job", help="Saved searches/tag presets job."
    ),
    skip_firestore: bool = typer.Option(False, "--skip-firestore", help="Skip Firestore refresh job."),
    skip_vertex: bool = typer.Option(False, "--skip-vertex", help="Skip Vertex import job."),
    skip_sql: bool = typer.Option(False, "--skip-sql", help="Skip SQL/Firestore sync job."),
    skip_bigquery: bool = typer.Option(False, "--skip-bigquery", help="Skip BigQuery refresh job."),
    skip_gcs_assets: bool = typer.Option(False, "--skip-gcs-assets", help="Skip GCS asset sync job."),
    skip_reports: bool = typer.Option(False, "--skip-reports", help="Skip reports/dossiers job."),
    skip_saved_searches: bool = typer.Option(False, "--skip-saved-searches", help="Skip saved searches job."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print planned commands without executing."),
    verify_only: bool = typer.Option(False, "--verify-only", help="Only run verification smokes."),
    run_smoke: bool = typer.Option(False, "--run-smoke", help="Run Cloud Run intake smoke after bootstrap."),
    report_dir: Path = typer.Option(
        Path("data/reports/dev_bootstrap"), "--report-dir", help="Directory to write JSON/Markdown reports."
    ),
    force: bool = typer.Option(False, "--force", help="Allow targeting non-dev projects (never prod)."),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging verbosity (DEBUG/INFO/WARNING/ERROR)."),
    smoke_api_url: str = typer.Option(
        "https://fastapi-gateway-y5jge5w2cq-uc.a.run.app", "--smoke-api-url", help="API base URL for smoke."
    ),
    smoke_token: str = typer.Option("dev-analyst-token", "--smoke-token", help="API token for smoke."),
    smoke_job: str = typer.Option("process-intakes", "--smoke-job", help="Cloud Run job to execute for smoke."),
    smoke_container: str = typer.Option("container-0", "--smoke-container", help="Container for smoke job."),
) -> None:
    """Run the dev bootstrap orchestrator."""

    _deprecated_env_notice("dev <reset|load|verify|smoke>")
    _run_bootstrap_dev(
        project=project,
        region=region,
        bundle_uri=bundle_uri,
        dataset=dataset,
        wif_service_account=wif_service_account,
        firestore_job=firestore_job,
        vertex_job=vertex_job,
        sql_job=sql_job,
        bigquery_job=bigquery_job,
        gcs_assets_job=gcs_assets_job,
        reports_job=reports_job,
        saved_searches_job=saved_searches_job,
        skip_firestore=skip_firestore,
        skip_vertex=skip_vertex,
        skip_sql=skip_sql,
        skip_bigquery=skip_bigquery,
        skip_gcs_assets=skip_gcs_assets,
        skip_reports=skip_reports,
        skip_saved_searches=skip_saved_searches,
        dry_run=dry_run,
        verify_only=verify_only,
        run_smoke=run_smoke,
        report_dir=report_dir,
        force=force,
        log_level=log_level,
        smoke_api_url=smoke_api_url,
        smoke_token=smoke_token,
        smoke_job=smoke_job,
        smoke_container=smoke_container,
    )


@env_app.command("seed-sample", help="Enqueue the sample dossier plan into the local queue store.")
def env_seed_sample() -> None:
    """Insert a sample dossier plan for quick smoke testing."""

    _deprecated_env_notice("seed-sample")
    bootstrap_seed_sample()


@settings_app.command("export-manifest", help="Export settings manifest (JSON/YAML/Markdown).")
def settings_export_manifest(
    proto_docs_dir: Path = typer.Option(
        PROJECT_ROOT / "docs" / "config",
        "--proto-docs-dir",
        help="Directory in the core repo to write manifest artifacts.",
    ),
    docs_repo: Optional[Path] = typer.Option(
        None,
        "--docs-repo",
        help="Optional docs repo path to mirror outputs (writes to book/config).",
    ),
) -> None:
    """Generate settings manifests and optional docs copies."""

    from scripts import export_settings_manifest as esm

    records = esm.build_manifest()
    target_dir = esm.ensure_directory(proto_docs_dir)
    esm.write_json(records, target_dir)
    esm.write_yaml(records, target_dir)
    esm.write_markdown(records, target_dir)
    if docs_repo:
        esm.write_docs_repo(records, docs_repo)


@settings_app.command("info", help="Show configuration precedence and resolved settings files.")
def settings_info() -> None:
    """Display config sources and current environment profile."""

    settings = get_settings()
    default_path = PROJECT_ROOT / "config" / "settings.default.toml"
    local_path = PROJECT_ROOT / "config" / "settings.local.toml"
    typer.echo("Configuration precedence:")
    typer.echo("1) settings.default.toml")
    typer.echo("2) settings.local.toml (optional)")
    typer.echo("3) env vars I4G_* with __ for nesting")
    typer.echo("4) CLI flags")
    typer.echo("")
    typer.echo(f"Resolved I4G_ENV: {settings.env}")
    typer.echo(f"Default file: {default_path} {'(missing)' if not default_path.exists() else ''}")
    typer.echo(f"Local file:   {local_path} {'(missing)' if not local_path.exists() else ''}")
    typer.echo("Env var prefix: I4G_ (use double underscores for nested fields, e.g., I4G_VECTOR__BACKEND)")


@smoke_app.command("dossiers", help="Verify dossier artifacts and signature manifests via API.")
def smoke_dossiers(
    api_url: str = typer.Option("http://localhost:8000", "--api-url", help="FastAPI base URL."),
    token: Optional[str] = typer.Option(None, "--token", help="API key for authenticated endpoints."),
    status: str = typer.Option("completed", "--status", help="Queue status filter."),
    limit: int = typer.Option(10, "--limit", help="Max dossiers to inspect."),
    plan_id: Optional[str] = typer.Option(None, "--plan-id", help="Specific dossier plan_id to verify."),
) -> None:
    """Run dossier smoke verification and hash checks."""

    from scripts import smoke_dossiers as smoke

    args = SimpleNamespace(api_url=api_url, token=token, status=status, limit=limit, plan_id=plan_id)
    try:
        result = smoke.run_smoke(args)
    except smoke.SmokeError as exc:  # type: ignore[attr-defined]
        typer.echo(f"SMOKE FAILED: {exc}", err=True)
        raise typer.Exit(code=1)
    typer.echo(
        "SMOKE OK: plan=%s verified, manifest=%s, signature=%s"
        % (result.plan_id, result.manifest_path or "<none>", result.signature_path or "<none>")
    )


@smoke_app.command("vertex-search", help="Run vertex retrieval smoke script.")
def smoke_vertex_search(extra_args: Optional[list[str]] = typer.Argument(None)) -> None:
    """Run Vertex smoke: dry-run ingest then query."""

    args = SimpleNamespace(
        project=None,
        location="global",
        data_store_id=None,
        jsonl="data/retrieval_poc/cases.jsonl",
        serving_config_id="default_search",
        query="wallet address verification",
        page_size=5,
    )
    if extra_args:
        # Preserve backward compat: allow positional overrides similar to old script flags.
        # Expected order: project location data_store_id jsonl serving_config_id query page_size
        for idx, value in enumerate(extra_args):
            if idx == 0:
                args.project = value
            elif idx == 1:
                args.location = value
            elif idx == 2:
                args.data_store_id = value
            elif idx == 3:
                args.jsonl = value
            elif idx == 4:
                args.serving_config_id = value
            elif idx == 5:
                args.query = value
            elif idx == 6:
                args.page_size = int(value)

    if not args.project or not args.data_store_id:
        typer.echo("--project and --data-store-id are required (or pass as positional overrides).", err=True)
        raise typer.Exit(code=1)

    smoke.vertex_search_smoke(args)


@smoke_app.command("cloud-run", help="Run Cloud Run smoke script.")
def smoke_cloud_run(extra_args: Optional[list[str]] = typer.Argument(None)) -> None:
    """Run the dev Cloud Run intake smoke end-to-end."""

    args = SimpleNamespace(
        api_url=None,
        token=None,
        project=None,
        region=None,
        job=None,
        container=None,
    )
    if extra_args:
        for idx, value in enumerate(extra_args):
            if idx == 0:
                args.api_url = value
            elif idx == 1:
                args.token = value
            elif idx == 2:
                args.project = value
            elif idx == 3:
                args.region = value
            elif idx == 4:
                args.job = value
            elif idx == 5:
                args.container = value

    # Defaults preserved from the original script env fallbacks.
    args.api_url = (
        args.api_url or os.getenv("I4G_SMOKE_API_URL") or "https://fastapi-gateway-y5jge5w2cq-uc.a.run.app"
    ).rstrip("/")
    args.token = args.token or os.getenv("I4G_SMOKE_TOKEN") or "dev-analyst-token"
    args.project = args.project or os.getenv("I4G_SMOKE_PROJECT") or "i4g-dev"
    args.region = args.region or os.getenv("I4G_SMOKE_REGION") or "us-central1"
    args.job = args.job or os.getenv("I4G_SMOKE_JOB") or "process-intakes"
    args.container = args.container or os.getenv("I4G_SMOKE_CONTAINER") or "container-0"

    smoke.cloud_run_smoke(args)


@jobs_app.command("ingest", help="Run ingestion job (same as i4g-ingest-job entrypoint).")
def jobs_ingest() -> None:
    from i4g.worker.jobs import ingest

    _exit_from_return(ingest.main())


@jobs_app.command("report", help="Run report job (same as i4g-report-job entrypoint).")
def jobs_report() -> None:
    from i4g.worker.jobs import report

    _exit_from_return(report.main())


@jobs_app.command("intake", help="Run intake job (same as i4g-intake-job entrypoint).")
def jobs_intake() -> None:
    from i4g.worker.jobs import intake

    _exit_from_return(intake.main())


@jobs_app.command("account", help="Run account list job (same as i4g-account-job entrypoint).")
def jobs_account() -> None:
    from i4g.worker.jobs import account_list

    _exit_from_return(account_list.main())


@jobs_app.command("ingest-retry", help="Run ingestion retry job (same as i4g-ingest-retry-job entrypoint).")
def jobs_ingest_retry() -> None:
    from i4g.worker.jobs import ingest_retry

    _exit_from_return(ingest_retry.main())


@jobs_app.command("dossier", help="Run dossier queue job (same as i4g-dossier-job entrypoint).")
def jobs_dossier() -> None:
    from i4g.worker.jobs import dossier_queue

    _exit_from_return(dossier_queue.main())


@ingest_app.command("bundles", help="Ingest bundle JSONL files.")
def ingest_bundles(
    input_path: Path = typer.Option(..., "--input", exists=True, readable=True, help="Path to JSONL bundle file."),
    limit: int = typer.Option(0, "--limit", help="Optional limit on number of records (0 = all)."),
) -> None:
    args = SimpleNamespace(input=input_path, limit=limit)
    ingest.ingest_bundles(args)


@ingest_app.command("vertex", help="Ingest data into Vertex search.")
def ingest_vertex(
    project: Optional[str] = typer.Option(None, "--project", help="GCP project hosting the Discovery data store."),
    location: str = typer.Option("global", "--location", help="Discovery location."),
    data_store_id: str = typer.Option(..., "--data-store-id", help="Discovery data store identifier."),
    jsonl: Path = typer.Option(..., "--jsonl", exists=True, readable=True, help="JSONL file of cases to ingest."),
    branch_id: str = typer.Option("default_branch", "--branch-id", help="Branch to import documents into."),
    dataset: Optional[str] = typer.Option(None, "--dataset", help="Dataset identifier injected when missing."),
    batch_size: int = typer.Option(50, "--batch-size", help="Documents per import batch."),
    reconcile_mode: str = typer.Option("INCREMENTAL", "--reconcile-mode", help="Reconciliation mode."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview first record without API calls."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    args = SimpleNamespace(
        project=project,
        location=location,
        branch_id=branch_id,
        data_store_id=data_store_id,
        jsonl=jsonl,
        dataset=dataset,
        batch_size=batch_size,
        reconcile_mode=reconcile_mode,
        dry_run=dry_run,
        verbose=verbose,
    )
    exit_code = ingest.ingest_vertex_search(args)
    if exit_code != 0:
        raise typer.Exit(code=exit_code)


@ingest_app.command("tag-saved-searches", help="Tag saved searches in bulk.")
def ingest_tag_saved_searches(
    input_path: Path = typer.Option(..., "--input", exists=True, readable=True, help="Path to JSON export file."),
    output_path: Optional[Path] = typer.Option(None, "--output", help="Destination file (defaults to input)."),
    tag: Optional[str] = typer.Option(None, "--tag", help="Tag to append; defaults to settings value."),
    schema_version: Optional[str] = typer.Option(
        None, "--schema-version", help="Schema version to set in params; defaults to settings value."
    ),
    dedupe: bool = typer.Option(True, "--dedupe/--no-dedupe", help="Remove duplicate tags (case-insensitive)."),
) -> None:
    args = SimpleNamespace(
        input=input_path,
        output=output_path,
        tag=tag,
        schema_version=schema_version,
        dedupe=dedupe,
    )
    ingest.tag_saved_searches(args)


@search_app.command("query-vertex", help="Query Vertex AI Search data store.")
def search_query_vertex(
    query: str = typer.Argument(..., help="Free-text query string to execute."),
    project: Optional[str] = typer.Option(None, "--project", help="GCP project hosting the Discovery data store."),
    location: str = typer.Option("global", "--location", help="Discovery location."),
    data_store_id: str = typer.Option(..., "--data-store-id", help="Discovery data store identifier."),
    serving_config_id: str = typer.Option(
        "default_search",
        "--serving-config-id",
        help="Serving config identifier (default: default_search).",
    ),
    page_size: int = typer.Option(5, "--page-size", help="Maximum number of results to return."),
    filter_expression: Optional[str] = typer.Option(None, "--filter", help="Discovery filter expression."),
    boost_json: Optional[str] = typer.Option(None, "--boost-json", help="BoostSpec payload as JSON."),
    raw: bool = typer.Option(False, "--raw", help="Print raw JSON response instead of a formatted summary."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    settings = get_settings()
    if verbose:
        typer.echo("[debug] Running Vertex query...", err=True)
    search.query_vertex(
        SimpleNamespace(
            query=query,
            project=project or settings.vector.vertex_ai_project,
            location=location,
            data_store_id=data_store_id,
            serving_config_id=serving_config_id,
            page_size=page_size,
            filter_expression=filter_expression,
            boost_json=boost_json,
            raw=raw,
            verbose=verbose,
        )
    )


@search_app.command("eval-vertex", help="Evaluate Vertex retrieval against scenarios.")
def search_eval_vertex(
    project: Optional[str] = typer.Option(None, "--project", help="GCP project hosting the Discovery data store."),
    location: str = typer.Option("global", "--location", help="Discovery location."),
    data_store_id: str = typer.Option(..., "--data-store-id", help="Discovery data store identifier."),
    serving_config_id: str = typer.Option(
        "default_search",
        "--serving-config-id",
        help="Serving config identifier (default: default_search).",
    ),
    config: Optional[Path] = typer.Option(None, "--config", exists=True, readable=True, help="JSON scenario file."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    settings = get_settings()
    exit_code = search.evaluate_vertex(
        SimpleNamespace(
            project=project or settings.vector.vertex_ai_project,
            location=location,
            data_store_id=data_store_id,
            serving_config_id=serving_config_id,
            config=config,
            verbose=verbose,
        )
    )
    if exit_code != 0:
        raise typer.Exit(code=exit_code)


@search_app.command("snapshot-schema", help="Refresh hybrid schema snapshot.")
def search_snapshot_schema(
    api_base: str = typer.Option("http://127.0.0.1:8000", "--api-base", help="FastAPI base URL."),
    api_key: Optional[str] = typer.Option(None, "--api-key", help="API key with analyst scope."),
    output: Path = typer.Option(Path("docs/examples/reviews_search_schema.json"), "--output", help="Destination file."),
    indent: int = typer.Option(2, "--indent", help="JSON indentation level."),
    timeout: float = typer.Option(30.0, "--timeout", help="HTTP timeout seconds."),
) -> None:
    search.refresh_hybrid_schema_snapshot(
        SimpleNamespace(api_base=api_base, api_key=api_key, output=output, indent=indent, timeout=timeout)
    )


@search_app.command("annotate-saved-searches", help="Annotate saved-search exports with tags/schema version.")
def search_annotate_saved_searches(
    input_path: Path = typer.Option(..., "--input", exists=True, readable=True, help="Path to JSON export file."),
    output_path: Optional[Path] = typer.Option(None, "--output", help="Destination file (defaults to input)."),
    tag: Optional[str] = typer.Option(None, "--tag", help="Tag to append; defaults to settings value."),
    schema_version: Optional[str] = typer.Option(
        None, "--schema-version", help="Schema version to set in params; defaults to settings value."
    ),
    dedupe: bool = typer.Option(True, "--dedupe/--no-dedupe", help="Remove duplicate tags (case-insensitive)."),
) -> None:
    """Wrap saved_searches.annotate_file into the CLI."""

    from i4g.scripts import saved_searches

    settings = saved_searches.SETTINGS
    effective_tag = tag if tag is not None else settings.search.saved_search.migration_tag
    effective_schema = schema_version if schema_version is not None else settings.search.saved_search.schema_version
    destination, count = saved_searches.annotate_file(
        input_path,
        output_path=output_path,
        tag=effective_tag or "",
        schema_version=effective_schema or "",
        dedupe=dedupe,
    )
    typer.echo(f"Annotated {count} saved search(es); wrote {destination}")


@data_app.command("prepare-retrieval-dataset", help="Prepare retrieval dataset artifacts.")
def data_prepare_retrieval_dataset(
    seed: int = typer.Option(1337, "--seed", help="Random seed."),
    count: Optional[int] = typer.Option(None, "--count", help="Total cases to generate."),
    include_templates: Optional[list[str]] = typer.Option(
        None, "--include-templates", help="Limit to template labels."
    ),
    template_config: Optional[Path] = typer.Option(
        None, "--template-config", exists=True, readable=True, help="JSON template spec file."
    ),
    output_dir: Path = typer.Option(Path("data/retrieval_poc"), "--output-dir", help="Destination directory."),
    case_file: str = typer.Option("cases.jsonl", "--case-file", help="Cases JSONL filename."),
    ground_truth: str = typer.Option("ground_truth.yaml", "--ground-truth", help="Ground truth YAML filename."),
    manifest: str = typer.Option("manifest.json", "--manifest", help="Manifest JSON filename."),
) -> None:
    args = SimpleNamespace(
        seed=seed,
        count=count,
        include_templates=include_templates,
        template_config=template_config,
        output_dir=output_dir,
        case_file=case_file,
        ground_truth=ground_truth,
        manifest=manifest,
    )
    code = datasets.generate_dataset(args)
    if code:
        raise typer.Exit(code)


@data_app.command("generate-coverage", help="Generate synthetic coverage bundle artifacts.")
def data_generate_coverage(
    output_dir: Path = typer.Option(
        Path("data/bundles/synthetic_coverage"),
        "--output-dir",
        help="Destination directory for artifacts.",
    ),
    seed: int = typer.Option(1337, "--seed", help="Random seed."),
    include_scenarios: Optional[list[str]] = typer.Option(
        None, "--include", help="Restrict generation to specific scenario names."
    ),
    smoke: bool = typer.Option(False, "--smoke", help="Generate the small smoke slice."),
    total_count: Optional[int] = typer.Option(
        None,
        "--total-count",
        help="Override total case count (evenly distributed across included scenarios).",
    ),
) -> None:
    result = synthetic_coverage.generate_bundle(
        output_dir=output_dir, seed=seed, include=include_scenarios, smoke=smoke, total_count=total_count
    )
    typer.echo(
        "Generated synthetic coverage bundle -> %s (cases=%d)" % (result.manifest_path.parent, result.case_count)
    )


@data_app.command("bundle-manifest", help="Build manifest with hashes and counts for a bundle directory.")
def data_bundle_manifest(
    bundle_dir: Path = typer.Option(
        ..., "--bundle-dir", exists=True, file_okay=False, dir_okay=True, readable=True, resolve_path=True
    ),
    bundle_id: Optional[str] = typer.Option(None, "--bundle-id", help="Identifier; defaults to directory name."),
    provenance: Optional[str] = typer.Option(None, "--provenance", help="Source or provenance note."),
    license_name: Optional[str] = typer.Option(None, "--license", help="License identifier or name."),
    tags: Optional[list[str]] = typer.Option(None, "--tag", help="Tag to record (repeatable)."),
    pii: bool = typer.Option(False, "--pii/--no-pii", help="Mark whether the bundle contains PII."),
    output: Optional[Path] = typer.Option(None, "--output", help="Manifest output path."),
) -> None:
    target_path = output or (bundle_dir / "manifest.generated.json")
    result = bundle_manifest.build_manifest(
        bundle_dir=bundle_dir,
        bundle_id=bundle_id or bundle_dir.name,
        provenance=provenance,
        license_name=license_name,
        tags=tags or [],
        pii=pii,
        output_path=target_path,
    )
    typer.echo(f"Wrote bundle manifest -> {result.output_path}")


@data_app.command("provision-bundle-bucket", help="Create or update the bundle GCS bucket with versioning and IAM.")
def data_provision_bundle_bucket(
    bucket: str = typer.Option(..., "--bucket", help="Bucket name to create or update."),
    project: str = typer.Option("i4g-dev", "--project", help="GCP project ID."),
    location: str = typer.Option("us-central1", "--location", help="GCS location."),
    storage_class: str = typer.Option("STANDARD", "--storage-class", help="GCS storage class."),
    retention_days: Optional[int] = typer.Option(None, "--retention-days", help="Retention policy in days (optional)."),
    delete_noncurrent_days: Optional[int] = typer.Option(
        365, "--delete-noncurrent-days", help="Delete noncurrent versions after this many days."
    ),
    iam_member: Optional[list[str]] = typer.Option(
        None,
        "--iam-member",
        help="IAM member to grant storage.objectAdmin on the bucket (repeatable).",
    ),
) -> None:
    result = bundle_storage.provision_bucket(
        bucket_name=bucket,
        project=project,
        location=location,
        storage_class=storage_class,
        retention_days=retention_days,
        delete_noncurrent_days=delete_noncurrent_days,
        iam_members=iam_member or [],
    )
    typer.echo(
        "Provisioned bundle bucket %s (project=%s, location=%s, versioning=%s, retention=%s, delete_noncurrent_days=%s)"
        % (
            result.bucket,
            result.project,
            result.location,
            result.versioning_enabled,
            result.retention_seconds,
            result.delete_noncurrent_after_days,
        )
    )


@data_app.command("build-index", help="Build vector/structured index.")
def data_build_index(
    input_path: Path = typer.Option(Path("data/ocr_output.json"), "--input", help="OCR results JSON."),
    backend: str = typer.Option("faiss", "--backend", help="Vector backend to use."),
    persist_dir: Optional[Path] = typer.Option(None, "--persist-dir", help="Override persistence directory."),
    model: str = typer.Option("nomic-embed-text", "--model", help="Embedding model name."),
    reset: bool = typer.Option(False, "--reset", help="Remove existing index before building."),
) -> None:
    args = SimpleNamespace(input=input_path, backend=backend, persist_dir=persist_dir, model=model, reset=reset)
    code = indexing.build_index(args)
    if code:
        raise typer.Exit(code)


@reports_app.command("verify-hashes", help="Verify dossier hashes on disk.")
def reports_verify_hashes(
    path: Optional[Path] = typer.Option(
        None, "--path", help="Manifest file or directory (defaults to data/reports/dossiers)."
    ),
    fail_on_warn: bool = typer.Option(False, "--fail-on-warn", help="Exit non-zero when warnings are present."),
) -> None:
    args = SimpleNamespace(path=path, fail_on_warn=fail_on_warn)
    code = reports_tasks.verify_dossier_hashes(args)
    if code:
        raise typer.Exit(code)


@reports_app.command("verify-ingestion-run", help="Inspect an ingestion run for missing artifacts.")
def reports_verify_ingestion(
    run_id: Optional[str] = typer.Option(None, "--run-id", help="Explicit run_id to inspect."),
    dataset: Optional[str] = typer.Option(None, "--dataset", help="Filter runs to a dataset before selecting latest."),
    status: str = typer.Option("succeeded", "--status", help="Expected run status."),
    expect_case_count: Optional[int] = typer.Option(None, "--expect-case-count", help="Exact case_count expected."),
    min_case_count: Optional[int] = typer.Option(None, "--min-case-count", help="Minimum acceptable case_count."),
    expect_sql_writes: Optional[int] = typer.Option(None, "--expect-sql-writes", help="Exact sql_writes expected."),
    expect_firestore_writes: Optional[int] = typer.Option(
        None, "--expect-firestore-writes", help="Exact firestore_writes expected."
    ),
    expect_vertex_writes: Optional[int] = typer.Option(
        None, "--expect-vertex-writes", help="Exact vertex_writes expected."
    ),
    max_retry_count: Optional[int] = typer.Option(None, "--max-retry-count", help="Upper bound for retry_count."),
    require_vector_enabled: bool = typer.Option(
        False, "--require-vector-enabled", help="Assert vector_enabled is true."
    ),
    allow_partial: bool = typer.Option(False, "--allow-partial", help="Permit partial runs (overrides status)."),
    verbose: bool = typer.Option(False, "--verbose", help="Print the selected row."),
) -> None:
    args = SimpleNamespace(
        run_id=run_id,
        dataset=dataset,
        status=status,
        expect_case_count=expect_case_count,
        min_case_count=min_case_count,
        expect_sql_writes=expect_sql_writes,
        expect_firestore_writes=expect_firestore_writes,
        expect_vertex_writes=expect_vertex_writes,
        max_retry_count=max_retry_count,
        require_vector_enabled=require_vector_enabled,
        allow_partial=allow_partial,
        verbose=verbose,
    )
    code = reports_tasks.verify_ingestion_run(args)
    if code:
        raise typer.Exit(code)


@extract_app.command("ocr", help="Run OCR pipeline against chat screenshots.")
def extract_ocr(
    input_path: Path = typer.Option(..., "--input", exists=True, readable=True, help="Folder of images."),
    output_path: Path = typer.Option(Path("data/ocr_output.json"), "--output", help="Output JSON path."),
) -> None:
    code = extract_tasks.ocr(SimpleNamespace(input=input_path, output=output_path))
    if code:
        raise typer.Exit(code)


@extract_app.command("extraction", help="Run extraction pipeline.")
def extract_extraction(
    input_path: Path = typer.Option(Path("data/ocr_output.json"), "--input", help="OCR output JSON."),
    output_path: Path = typer.Option(Path("data/entities.json"), "--output", help="Structured entities output."),
) -> None:
    code = extract_tasks.extraction(SimpleNamespace(input=input_path, output=output_path))
    if code:
        raise typer.Exit(code)


@extract_app.command("semantic", help="Run semantic extraction pipeline.")
def extract_semantic(
    input_path: Path = typer.Option(Path("data/ocr_output.json"), "--input", help="OCR output JSON."),
    output_path: Path = typer.Option(Path("data/entities_semantic.json"), "--output", help="Semantic entities output."),
    model: str = typer.Option("llama3.1", "--model", help="Semantic extractor model."),
) -> None:
    code = extract_tasks.semantic(SimpleNamespace(input=input_path, output=output_path, model=model))
    if code:
        raise typer.Exit(code)


@extract_app.command("lea-pilot", help="Run LEA pilot pipeline.")
def extract_lea_pilot() -> None:
    code = extract_tasks.lea_pilot(SimpleNamespace())
    if code:
        raise typer.Exit(code)


@admin_app.command("query", help="Run scam-detection RAG query using the configured vector backend.")
def admin_query(
    question: str = typer.Option(..., "--question", "-q", help="Free-text question to analyze."),
    backend: Optional[str] = typer.Option(
        None,
        "--backend",
        case_sensitive=False,
        help="Vector backend to use (overrides I4G_VECTOR_BACKEND).",
    ),
) -> None:
    """Run scam-detection query via local RAG helper."""

    settings = get_settings()
    search.run_query(SimpleNamespace(question=question, backend=backend or settings.vector.backend))


@admin_app.command("vertex-search", help="Query Vertex AI Search (Discovery) data store.")
def admin_vertex_search(
    query: str = typer.Argument(..., help="Free-text query string to execute."),
    project: Optional[str] = typer.Option(None, "--project", help="GCP project hosting the Discovery data store."),
    location: Optional[str] = typer.Option(None, "--location", help="Discovery location (default: global)."),
    data_store_id: str = typer.Option(..., "--data-store-id", help="Discovery data store identifier."),
    serving_config_id: str = typer.Option(
        "default_search",
        "--serving-config-id",
        help="Serving config identifier (default: default_search).",
    ),
    page_size: int = typer.Option(5, "--page-size", help="Maximum number of results to return."),
    filter_expression: Optional[str] = typer.Option(None, "--filter", help="Discovery filter expression."),
    boost_json: Optional[str] = typer.Option(None, "--boost-json", help="Optional BoostSpec payload as JSON."),
    raw: bool = typer.Option(False, "--raw", help="Print raw JSON response instead of a formatted summary."),
) -> None:
    """Run Vertex Search helper."""

    settings = get_settings()
    search.run_vertex_search(
        SimpleNamespace(
            query=query,
            project=project or settings.vector.vertex_ai_project,
            location=location or settings.vector.vertex_ai_location or "global",
            data_store_id=data_store_id,
            serving_config_id=serving_config_id,
            page_size=page_size,
            filter_expression=filter_expression,
            boost_json=boost_json,
            raw=raw,
        )
    )


@admin_app.command("export-saved-searches", help="Export saved searches to JSON.")
def admin_export_saved_searches(
    limit: int = typer.Option(100, "--limit", help="Max entries to export."),
    include_all: bool = typer.Option(False, "--all", help="Include shared searches along with personal ones."),
    owner: Optional[str] = typer.Option(None, "--owner", help="Filter by owner username (ignored if --all)."),
    output: Optional[Path] = typer.Option(None, "--output", help="Output file; omit for stdout."),
    split: bool = typer.Option(False, "--split", help="When writing to a folder, create one file per owner."),
    include_tags: Optional[list[str]] = typer.Option(
        None,
        "--include-tags",
        help="Only export saved searches with these tags.",
    ),
    schema_version: Optional[str] = typer.Option(
        None,
        "--schema-version",
        help="Optional schema version to inject into exported search params.",
    ),
) -> None:
    """Proxy to saved-search export helper while keeping Typer UX."""

    saved_searches.export_saved_searches(
        SimpleNamespace(
            limit=limit,
            all=include_all,
            owner=owner,
            output=str(output) if output else None,
            split=split,
            include_tags=include_tags,
            schema_version=schema_version or (get_settings().search.saved_search.schema_version),
        )
    )


@admin_app.command("import-saved-searches", help="Import saved searches from JSON.")
def admin_import_saved_searches(
    input_path: Optional[Path] = typer.Option(None, "--input", help="JSON file path (defaults to stdin)."),
    owner: Optional[str] = typer.Option(None, "--owner", help="Owner username (default: current user)."),
    shared: bool = typer.Option(False, "--shared", help="Import into shared scope (owner=NULL)."),
    include_tags: Optional[list[str]] = typer.Option(
        None,
        "--include-tags",
        help="Only import searches with these tags.",
    ),
) -> None:
    """Proxy to saved-search import helper."""

    saved_searches.import_saved_searches(
        SimpleNamespace(
            input=str(input_path) if input_path else None,
            owner=owner,
            shared=shared,
            include_tags=include_tags,
        )
    )


@admin_app.command("prune-saved-searches", help="Delete saved searches by owner/tag filters.")
def admin_prune_saved_searches(
    owner: Optional[str] = typer.Option(None, "--owner", help="Delete saved searches belonging to this owner."),
    tags: Optional[list[str]] = typer.Option(
        None,
        "--tags",
        help="Only delete saved searches containing these tags.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview deletions without applying them."),
) -> None:
    """Proxy to saved-search prune helper."""

    saved_searches.prune_saved_searches(SimpleNamespace(owner=owner, tags=tags, dry_run=dry_run))


@admin_app.command("bulk-update-tags", help="Add, remove, or replace saved-search tags in bulk.")
def admin_bulk_update_tags(
    owner: Optional[str] = typer.Option(None, "--owner", help="Filter saved searches to this owner."),
    tags: Optional[list[str]] = typer.Option(
        None,
        "--tags",
        help="Only target saved searches containing these tags.",
    ),
    search_id: Optional[list[str]] = typer.Option(
        None,
        "--search-id",
        help="Explicit saved search IDs to update.",
    ),
    add: Optional[list[str]] = typer.Option(None, "--add", help="Tags to add to each matched saved search."),
    remove: Optional[list[str]] = typer.Option(
        None,
        "--remove",
        help="Tags to remove from each matched saved search.",
    ),
    replace: Optional[list[str]] = typer.Option(
        None,
        "--replace",
        help="Replace the existing tag set with this list (overrides --add/--remove).",
    ),
    limit: int = typer.Option(200, "--limit", help="Max saved searches to inspect when filtering."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview the changes without persisting them."),
) -> None:
    """Proxy to bulk tag update helper."""

    saved_searches.bulk_update_saved_search_tags(
        SimpleNamespace(
            owner=owner,
            tags=tags,
            search_id=search_id,
            add=add,
            remove=remove,
            replace=replace,
            limit=limit,
            dry_run=dry_run,
        )
    )


@admin_app.command("export-tag-presets", help="Export tag presets derived from saved searches.")
def admin_export_tag_presets(
    owner: Optional[str] = typer.Option(None, "--owner", help="Filter presets to this owner (omit for shared)."),
    output: Optional[Path] = typer.Option(None, "--output", help="File to write JSON (stdout if omitted)."),
) -> None:
    """Proxy to tag preset export helper."""

    saved_searches.export_tag_presets(SimpleNamespace(owner=owner, output=str(output) if output else None))


@admin_app.command("import-tag-presets", help="Import tag presets and append as filter presets.")
def admin_import_tag_presets(
    input_path: Optional[Path] = typer.Option(None, "--input", help="JSON file path (defaults to stdin)."),
) -> None:
    """Proxy to tag preset import helper."""

    saved_searches.import_tag_presets(SimpleNamespace(input=str(input_path) if input_path else None))


@admin_app.command("build-dossiers", help="Group accepted cases into dossier queue entries.")
def admin_build_dossiers(
    limit: int = typer.Option(200, "--limit", help="Number of accepted cases to inspect."),
    min_loss: Optional[float] = typer.Option(None, "--min-loss", help="Minimum loss threshold in USD."),
    recency_days: Optional[int] = typer.Option(None, "--recency-days", help="Accepted-within window in days."),
    max_cases: Optional[int] = typer.Option(None, "--max-cases", help="Maximum number of cases per dossier."),
    jurisdiction_mode: str = typer.Option(
        "single",
        "--jurisdiction-mode",
        help="Grouping strategy for jurisdictions (single|multi|global).",
    ),
    cross_border_only: bool = typer.Option(
        False,
        "--cross-border-only",
        help="Require cross-border cases regardless of settings.report.require_cross_border.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show bundles without enqueuing them."),
    preview: int = typer.Option(5, "--preview", help="How many plans to display during --dry-run."),
) -> None:
    """Proxy to dossier build helper."""

    dossiers.build_dossiers(
        SimpleNamespace(
            limit=limit,
            min_loss=min_loss,
            recency_days=recency_days,
            max_cases=max_cases,
            jurisdiction_mode=jurisdiction_mode,
            cross_border_only=cross_border_only,
            dry_run=dry_run,
            preview=preview,
        )
    )


@admin_app.command("process-dossiers", help="Lease queued dossier plans and render artifacts.")
def admin_process_dossiers(
    batch_size: int = typer.Option(5, "--batch-size", help="Number of queue entries to lease this run."),
    preview: int = typer.Option(5, "--preview", help="How many plan results to display after processing."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Inspect queue entries without generating artifacts."),
    task_id: Optional[str] = typer.Option(
        None,
        "--task-id",
        help="Optional task identifier for Task_STATUS updates.",
    ),
    task_status_url: Optional[str] = typer.Option(
        None,
        "--task-status-url",
        help="FastAPI /tasks base URL.",
    ),
) -> None:
    """Proxy to dossier processing helper."""

    dossiers.process_dossiers(
        SimpleNamespace(
            batch_size=batch_size,
            preview=preview,
            dry_run=dry_run,
            task_id=task_id,
            task_status_url=task_status_url,
        )
    )


@admin_app.command("pilot-dossiers", help="Seed curated pilot cases and enqueue dossier plans.")
def admin_pilot_dossiers(
    cases_file: Path = typer.Option(
        pilot.DEFAULT_PILOT_CASES_PATH,
        "--cases-file",
        help="Path to JSON file containing pilot case specs.",
    ),
    cases: Optional[list[str]] = typer.Option(
        None,
        "--case",
        help="Specific case_id(s) to include (repeat flag or comma-separated).",
    ),
    case_count: Optional[int] = typer.Option(
        None,
        "--case-count",
        help="Limit the number of pilot cases after filtering.",
    ),
    seed_only: bool = typer.Option(False, "--seed-only", help="Seed pilot data without generating dossier plans."),
    min_loss: Optional[float] = typer.Option(None, "--min-loss", help="Minimum loss threshold in USD."),
    recency_days: Optional[int] = typer.Option(None, "--recency-days", help="Accepted-within window in days."),
    max_cases: Optional[int] = typer.Option(None, "--max-cases", help="Maximum number of cases per dossier."),
    jurisdiction_mode: str = typer.Option(
        "single",
        "--jurisdiction-mode",
        help="Grouping strategy for jurisdictions (single|multi|global).",
    ),
    cross_border_only: bool = typer.Option(
        False,
        "--cross-border-only",
        help="Require cross-border cases regardless of settings.report.require_cross_border.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview plan IDs without enqueuing pilot dossiers."),
) -> None:
    """Proxy to pilot dossier scheduler."""

    pilot.schedule_pilot_dossiers(
        SimpleNamespace(
            cases_file=cases_file,
            cases=cases,
            case_count=case_count,
            seed_only=seed_only,
            min_loss=min_loss,
            recency_days=recency_days,
            max_cases=max_cases,
            jurisdiction_mode=jurisdiction_mode,
            cross_border_only=cross_border_only,
            dry_run=dry_run,
        )
    )


if __name__ == "__main__":
    app()
