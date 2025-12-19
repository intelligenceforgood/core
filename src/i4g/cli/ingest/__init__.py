import typer
from pathlib import Path
from typing import Optional
from types import SimpleNamespace
from . import logic as ingest

ingest_app = typer.Typer(help="Ingestion utilities and helpers.")

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
    ingest.ingest_vertex_search(args)
