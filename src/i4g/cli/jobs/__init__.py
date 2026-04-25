import os
from pathlib import Path

import typer

jobs_app = typer.Typer(help="Invoke background jobs (ingest, report, intake, dossier, analytics).")


def _exit_from_return(code: int | None) -> None:
    """Honor integer return codes from invoked helpers."""

    if isinstance(code, int) and code != 0:
        raise typer.Exit(code)


@jobs_app.command("ingest", help="Run ingestion job.")
def jobs_ingest(
    bundle_uri: str | None = typer.Option(
        None, "--bundle-uri", help="Override bundle URI (sets I4G_INGEST__JSONL_PATH)."
    ),
    dataset: str | None = typer.Option(
        None, "--dataset", help="Override dataset name (sets I4G_INGEST__DATASET_NAME)."
    ),
    engagement_id: str | None = typer.Option(None, "--engagement-id", help="Assign ingested cases to this engagement."),
) -> None:
    if bundle_uri:
        os.environ["I4G_INGEST__JSONL_PATH"] = bundle_uri
    if dataset:
        os.environ["I4G_INGEST__DATASET_NAME"] = dataset
    if engagement_id:
        os.environ["I4G_INGEST__ENGAGEMENT_ID"] = engagement_id

    from i4g.worker.jobs import ingest

    _exit_from_return(ingest.main())


@jobs_app.command("report", help="Run report job.")
def jobs_report(
    bundle_uri: str | None = typer.Option(None, "--bundle-uri", help="Ignored (compatibility arg)."),
    dataset: str | None = typer.Option(None, "--dataset", help="Ignored (compatibility arg)."),
) -> None:
    from i4g.worker.jobs import report

    _exit_from_return(report.main())


@jobs_app.command("intake", help="Run intake job.")
def jobs_intake() -> None:
    from i4g.worker.jobs import intake

    _exit_from_return(intake.main())


@jobs_app.command("ingest-retry", help="Run ingestion retry job.")
def jobs_ingest_retry() -> None:
    from i4g.worker.jobs import ingest_retry

    _exit_from_return(ingest_retry.main())


@jobs_app.command("dossier", help="Run dossier queue job.")
def jobs_dossier() -> None:
    from i4g.worker.jobs import dossier_queue

    _exit_from_return(dossier_queue.main())


@jobs_app.command("sweeper", help="Run classification sweeper job.")
def jobs_sweeper() -> None:
    from i4g.worker.jobs import classification_sweeper

    classification_sweeper.run()


@jobs_app.command("retention-purge", help="Run data retention purge job.")
def jobs_retention_purge(
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview purge candidates without modifying data."),
) -> None:
    from i4g.worker.jobs import retention_purge

    _exit_from_return(retention_purge.main(dry_run=dry_run))


@jobs_app.command("evidence-integrity", help="Run evidence file integrity check.")
def jobs_evidence_integrity(
    backfill: bool = typer.Option(False, "--backfill", help="Backfill missing file_sha256 hashes before checking."),
    limit: int | None = typer.Option(None, "--limit", help="Maximum number of documents to check."),
) -> None:
    from i4g.worker.jobs import evidence_integrity

    _exit_from_return(evidence_integrity.main(backfill=backfill, limit=limit))


@jobs_app.command("analytics", help="Refresh pre-computed analytics aggregates.")
def jobs_analytics() -> None:
    from i4g.worker.jobs import analytics_aggregation

    _exit_from_return(analytics_aggregation.main())


@jobs_app.command("ingest-destroylist", help="Ingest the PhishDestroy destroylist (domain blocklist).")
def jobs_ingest_destroylist(
    data_path: Path | None = typer.Option(
        None,
        "--data-path",
        help="Override path to DestroyScammers/data/data.json (defaults to settings).",
    ),
) -> None:
    from i4g.worker.jobs import phishdestroy_destroylist

    _exit_from_return(phishdestroy_destroylist.main(data_path=data_path))


@jobs_app.command("merklemap-tail", help="Run the PhishDestroy merklemap SSE tail worker.")
def jobs_merklemap_tail(
    max_runtime_seconds: int | None = typer.Option(
        None,
        "--max-runtime-seconds",
        help="Stop after N seconds (default: run until SIGTERM).",
    ),
    max_events: int | None = typer.Option(
        None,
        "--max-events",
        help="Stop after N events (default: unbounded).",
    ),
) -> None:
    from i4g.worker.jobs import merklemap_tail

    _exit_from_return(
        merklemap_tail.main(
            max_runtime_seconds=max_runtime_seconds,
            max_events=max_events,
        )
    )


@jobs_app.command("bq-export", help="Export analytics aggregate tables to BigQuery.")
def jobs_bq_export(
    dry_run: bool = typer.Option(False, "--dry-run", help="Simulate export (print row counts without writing to BQ)."),
) -> None:
    from i4g.worker.jobs import bq_export

    _exit_from_return(bq_export.main(dry_run=dry_run))


@jobs_app.command("entity-extract", help="Batch entity extraction via LLM + rule-based NER.")
def jobs_entity_extract(
    backfill: bool = typer.Option(False, "--backfill", help="Re-extract entities for all cases, not just missing."),
    limit: int = typer.Option(0, "--limit", help="Max cases to process (0 = unlimited)."),
) -> None:
    from i4g.worker.jobs import entity_extract

    _exit_from_return(entity_extract.main(backfill=backfill, limit=limit))


@jobs_app.command("linkage-extract", help="Extract indicator links from intake narratives via LLM.")
def jobs_linkage_extract(
    backfill: bool = typer.Option(False, "--backfill", help="Process all intakes, not just unlinked ones."),
    mode: str = typer.Option("intake", "--mode", help="Processing mode: intake, cases, or all."),
) -> None:
    from i4g.worker.jobs import linkage_extract

    _exit_from_return(linkage_extract.main(backfill=backfill, mode=mode))


@jobs_app.command("watchlist-check", help="Check watchlist entities for new activity and generate alerts.")
def jobs_watchlist_check() -> None:
    from i4g.worker.jobs import watchlist_check

    _exit_from_return(watchlist_check.main())


@jobs_app.command("infrastructure-clustering", help="Discover shared-infrastructure edges between entities.")
def jobs_infrastructure_clustering() -> None:
    from i4g.worker.jobs import infrastructure_clustering

    _exit_from_return(infrastructure_clustering.main())


@jobs_app.command("takedown-check", help="Check known scam URLs for takedown status.")
def jobs_takedown_check() -> None:
    from i4g.worker.jobs import takedown_check

    _exit_from_return(takedown_check.main())


@jobs_app.command("scheduled-reports", help="Generate recurring reports for active schedules.")
def jobs_scheduled_reports() -> None:
    from i4g.worker.jobs import scheduled_reports

    _exit_from_return(scheduled_reports.main())


@jobs_app.command("auto-investigate", help="Trigger SSI investigations for uninvestigated URLs in cases.")
def jobs_auto_investigate(
    dry_run: bool = typer.Option(False, "--dry-run", help="Report what would be triggered without acting."),
    limit: int = typer.Option(100, "--limit", help="Max URLs to process per run."),
) -> None:
    from i4g.worker.jobs import auto_investigate

    _exit_from_return(auto_investigate.main(dry_run=dry_run, limit=limit))


@jobs_app.command("backup-db", help="Backup Cloud SQL database to GCS via pg_dump.")
def jobs_backup_db() -> None:
    from i4g.worker.jobs import backup_db

    _exit_from_return(backup_db.main())
