"""Reports command group."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import typer

from i4g.cli.reports import tasks

reports_app = typer.Typer(help="Report/dossier verification helpers.")


@reports_app.command("verify-hashes", help="Verify dossier hashes on disk.")
def reports_verify_hashes(
    path: Optional[Path] = typer.Option(
        None, "--path", help="Manifest file or directory (defaults to data/reports/dossiers)."
    ),
    fail_on_warn: bool = typer.Option(False, "--fail-on-warn", help="Exit non-zero when warnings are present."),
) -> None:
    args = SimpleNamespace(path=path, fail_on_warn=fail_on_warn)
    code = tasks.verify_dossier_hashes(args)
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
    code = tasks.verify_ingestion_run(args)
    if code:
        raise typer.Exit(code)
