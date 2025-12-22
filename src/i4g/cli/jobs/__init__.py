import os
from typing import Optional
import typer

jobs_app = typer.Typer(help="Invoke background jobs (ingest, report, intake, dossier, account).")


def _exit_from_return(code: int | None) -> None:
    """Honor integer return codes from invoked helpers."""

    if isinstance(code, int) and code != 0:
        raise typer.Exit(code)


@jobs_app.command("ingest", help="Run ingestion job.")
def jobs_ingest(
    bundle_uri: Optional[str] = typer.Option(
        None, "--bundle-uri", help="Override bundle URI (sets I4G_INGEST__JSONL_PATH)."
    ),
    dataset: Optional[str] = typer.Option(
        None, "--dataset", help="Override dataset name (sets I4G_INGEST__DATASET_NAME)."
    ),
) -> None:
    if bundle_uri:
        os.environ["I4G_INGEST__JSONL_PATH"] = bundle_uri
    if dataset:
        os.environ["I4G_INGEST__DATASET_NAME"] = dataset

    from i4g.worker.jobs import ingest

    _exit_from_return(ingest.main())


@jobs_app.command("report", help="Run report job.")
def jobs_report(
    bundle_uri: Optional[str] = typer.Option(None, "--bundle-uri", help="Ignored (compatibility arg)."),
    dataset: Optional[str] = typer.Option(None, "--dataset", help="Ignored (compatibility arg)."),
) -> None:
    from i4g.worker.jobs import report

    _exit_from_return(report.main())


@jobs_app.command("intake", help="Run intake job.")
def jobs_intake() -> None:
    from i4g.worker.jobs import intake

    _exit_from_return(intake.main())


@jobs_app.command("account", help="Run account list job.")
def jobs_account() -> None:
    from i4g.worker.jobs import account_list

    _exit_from_return(account_list.main())


@jobs_app.command("ingest-retry", help="Run ingestion retry job.")
def jobs_ingest_retry() -> None:
    from i4g.worker.jobs import ingest_retry

    _exit_from_return(ingest_retry.main())


@jobs_app.command("dossier", help="Run dossier queue job.")
def jobs_dossier() -> None:
    from i4g.worker.jobs import dossier_queue

    _exit_from_return(dossier_queue.main())
