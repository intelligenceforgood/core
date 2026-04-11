"""Typer commands for ``i4g bootstrap local``."""

from __future__ import annotations

from pathlib import Path

import typer

from .constants import REPORTS_DIR
from .orchestrator import run_local

local_app = typer.Typer(help="Bootstrap local sandbox data and verification smokes.")


def _exit_from_return(code: int | None) -> None:
    """Honor integer return codes from invoked helpers."""

    if isinstance(code, int) and code != 0:
        raise typer.Exit(code)


@local_app.command("reset", help="Wipe and reload local sandbox artifacts.")
def bootstrap_local_reset(
    skip_vector: bool = typer.Option(False, "--skip-vector", help="Skip rebuilding vector/structured stores."),
    bundle_uri: str | None = typer.Option(
        None, "--bundle-uri", help="Optional bundle JSONL path/URI to place into data/bundles."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print planned actions without mutating disk."),
    report_dir: Path = typer.Option(REPORTS_DIR, "--report-dir", help="Verification report directory."),
    smoke_search: bool = typer.Option(False, "--smoke-search", help="Run Vertex search smoke after verification."),
    search_project: str | None = typer.Option(
        None, "--search-project", help="Vertex project for search smoke (defaults to settings/env)."
    ),
    search_location: str | None = typer.Option(
        None, "--search-location", help="Vertex location for search smoke (default from settings/env)."
    ),
    search_data_store_id: str | None = typer.Option(
        None, "--search-data-store-id", help="Vertex data store id for search smoke."
    ),
    search_serving_config_id: str = typer.Option(
        "default_search", "--search-serving-config-id", help="Vertex serving config id for search smoke."
    ),
    search_query: str = typer.Option("wallet address verification", "--search-query", help="Search smoke query."),
    search_page_size: int = typer.Option(5, "--search-page-size", help="Search smoke page size."),
    smoke_dossiers: bool = typer.Option(False, "--smoke-dossiers", help="Run dossier verification smoke."),
    smoke_api_url: str | None = typer.Option(
        None, "--smoke-api-url", help="API base URL for dossier smoke (defaults to env or localhost)."
    ),
    smoke_token: str | None = typer.Option(None, "--smoke-token", help="API token for dossier smoke."),
    smoke_dossier_status: str = typer.Option(
        "completed", "--smoke-dossier-status", help="Queue status filter for dossier smoke."
    ),
    smoke_dossier_limit: int = typer.Option(5, "--smoke-dossier-limit", help="Maximum dossiers to inspect."),
    smoke_dossier_plan_id: str | None = typer.Option(
        None, "--smoke-dossier-plan-id", help="Specific dossier plan_id to verify during smoke."
    ),
    skip_ingest: bool = typer.Option(False, "--skip-ingest", help="Skip the potentially long bundle ingestion phase."),
    skip_extraction: bool = typer.Option(
        False,
        "--skip-extraction",
        help="Skip running extraction orchestrator during ingestion (use pre-labeled entities).",
    ),
    limit: int | None = typer.Option(None, "--limit", help="Limit number of records ingested per bundle."),
    force: bool = typer.Option(False, "--force", help="Allow running when I4G_ENV is not local."),
) -> None:
    """Reset local sandbox then reload sample data."""

    _exit_from_return(
        run_local(
            reset=True,
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
            skip_ingest=skip_ingest,
            skip_extraction=skip_extraction,
            limit=limit,
        )
    )


@local_app.command("load", help="Refresh local sandbox without wiping artifacts.")
def bootstrap_local_load(
    skip_vector: bool = typer.Option(False, "--skip-vector", help="Skip rebuilding vector/structured stores."),
    bundle_uri: str | None = typer.Option(
        None, "--bundle-uri", help="Optional bundle JSONL path/URI to place into data/bundles."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print planned actions without mutating disk."),
    report_dir: Path = typer.Option(REPORTS_DIR, "--report-dir", help="Verification report directory."),
    smoke_search: bool = typer.Option(False, "--smoke-search", help="Run Vertex search smoke after verification."),
    search_project: str | None = typer.Option(
        None, "--search-project", help="Vertex project for search smoke (defaults to settings/env)."
    ),
    search_location: str | None = typer.Option(
        None, "--search-location", help="Vertex location for search smoke (default from settings/env)."
    ),
    search_data_store_id: str | None = typer.Option(
        None, "--search-data-store-id", help="Vertex data store id for search smoke."
    ),
    search_serving_config_id: str = typer.Option(
        "default_search", "--search-serving-config-id", help="Vertex serving config id for search smoke."
    ),
    search_query: str = typer.Option("wallet address verification", "--search-query", help="Search smoke query."),
    search_page_size: int = typer.Option(5, "--search-page-size", help="Search smoke page size."),
    smoke_dossiers: bool = typer.Option(False, "--smoke-dossiers", help="Run dossier verification smoke."),
    smoke_api_url: str | None = typer.Option(
        None, "--smoke-api-url", help="API base URL for dossier smoke (defaults to env or localhost)."
    ),
    smoke_token: str | None = typer.Option(None, "--smoke-token", help="API token for dossier smoke."),
    smoke_dossier_status: str = typer.Option(
        "completed", "--smoke-dossier-status", help="Queue status filter for dossier smoke."
    ),
    smoke_dossier_limit: int = typer.Option(5, "--smoke-dossier-limit", help="Maximum dossiers to inspect."),
    smoke_dossier_plan_id: str | None = typer.Option(
        None, "--smoke-dossier-plan-id", help="Specific dossier plan_id to verify during smoke."
    ),
    force: bool = typer.Option(False, "--force", help="Allow running when I4G_ENV is not local."),
) -> None:
    """Refresh local sandbox data without a reset."""

    _exit_from_return(
        run_local(
            reset=False,
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
    )


@local_app.command("verify", help="Run verification only for the local sandbox.")
def bootstrap_local_verify(
    bundle_uri: str | None = typer.Option(
        None, "--bundle-uri", help="Optional bundle JSONL path/URI to place into data/bundles."
    ),
    report_dir: Path = typer.Option(REPORTS_DIR, "--report-dir", help="Verification report directory."),
    smoke_search: bool = typer.Option(False, "--smoke-search", help="Run Vertex search smoke after verification."),
    search_project: str | None = typer.Option(
        None, "--search-project", help="Vertex project for search smoke (defaults to settings/env)."
    ),
    search_location: str | None = typer.Option(
        None, "--search-location", help="Vertex location for search smoke (default from settings/env)."
    ),
    search_data_store_id: str | None = typer.Option(
        None, "--search-data-store-id", help="Vertex data store id for search smoke."
    ),
    search_serving_config_id: str = typer.Option(
        "default_search", "--search-serving-config-id", help="Vertex serving config id for search smoke."
    ),
    search_query: str = typer.Option("wallet address verification", "--search-query", help="Search smoke query."),
    search_page_size: int = typer.Option(5, "--search-page-size", help="Search smoke page size."),
    smoke_dossiers: bool = typer.Option(False, "--smoke-dossiers", help="Run dossier verification smoke."),
    smoke_api_url: str | None = typer.Option(
        None, "--smoke-api-url", help="API base URL for dossier smoke (defaults to env or localhost)."
    ),
    smoke_token: str | None = typer.Option(None, "--smoke-token", help="API token for dossier smoke."),
    smoke_dossier_status: str = typer.Option(
        "completed", "--smoke-dossier-status", help="Queue status filter for dossier smoke."
    ),
    smoke_dossier_limit: int = typer.Option(5, "--smoke-dossier-limit", help="Maximum dossiers to inspect."),
    smoke_dossier_plan_id: str | None = typer.Option(
        None, "--smoke-dossier-plan-id", help="Specific dossier plan_id to verify during smoke."
    ),
    force: bool = typer.Option(False, "--force", help="Allow running when I4G_ENV is not local."),
) -> None:
    """Emit local verification reports without regenerating data."""

    _exit_from_return(
        run_local(
            reset=False,
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
    )


@local_app.command("smoke", help="Alias for local verification-only checks.")
def bootstrap_local_smoke(
    bundle_uri: str | None = typer.Option(
        None, "--bundle-uri", help="Optional bundle JSONL path/URI to place into data/bundles."
    ),
    report_dir: Path = typer.Option(REPORTS_DIR, "--report-dir", help="Verification report directory."),
    smoke_search: bool = typer.Option(False, "--smoke-search", help="Run Vertex search smoke after verification."),
    smoke_dossiers: bool = typer.Option(False, "--smoke-dossiers", help="Run dossier verification smoke."),
    smoke_api_url: str | None = typer.Option(
        None, "--smoke-api-url", help="API base URL for dossier smoke (defaults to env or localhost)."
    ),
    smoke_token: str | None = typer.Option(None, "--smoke-token", help="API token for dossier smoke."),
    smoke_dossier_status: str = typer.Option(
        "completed", "--smoke-dossier-status", help="Queue status filter for dossier smoke."
    ),
    smoke_dossier_limit: int = typer.Option(5, "--smoke-dossier-limit", help="Maximum dossiers to inspect."),
    smoke_dossier_plan_id: str | None = typer.Option(
        None, "--smoke-dossier-plan-id", help="Specific dossier plan_id to verify during smoke."
    ),
    force: bool = typer.Option(False, "--force", help="Allow running when I4G_ENV is not local."),
) -> None:
    """Run local verification-only checks (smoke alias)."""

    _exit_from_return(
        run_local(
            reset=False,
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
    )


__all__ = ["local_app"]
