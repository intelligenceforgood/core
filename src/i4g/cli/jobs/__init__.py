import typer

jobs_app = typer.Typer(help="Invoke background jobs (ingest, report, intake, dossier, account).")


def _exit_from_return(code: int | None) -> None:
    """Honor integer return codes from invoked helpers."""

    if isinstance(code, int) and code != 0:
        raise typer.Exit(code)


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
