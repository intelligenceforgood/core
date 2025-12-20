"""Legacy Azure migration utilities (kept separate from the main i4g CLI)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer

PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

app = typer.Typer(add_completion=True, help="Legacy Azure migration and export helpers.")


def _run_script(relative_path: str, args: list[str] | None = None) -> None:
    """Execute a legacy migration script with passthrough arguments."""

    script_path = PROJECT_ROOT / relative_path
    cmd = [sys.executable, str(script_path)]
    if args:
        cmd.extend(args)
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise typer.Exit(result.returncode)


@app.command("azure-sql-to-firestore", help="Copy legacy Azure SQL intake tables into Firestore staging.")
def azure_sql_to_firestore(extra_args: Optional[list[str]] = typer.Argument(None)) -> None:
    _run_script("scripts/migration/azure_sql_to_firestore.py", extra_args or [])


@app.command("azure-blob-to-gcs", help="Sync Azure Blob Storage containers into GCS.")
def azure_blob_to_gcs(extra_args: Optional[list[str]] = typer.Argument(None)) -> None:
    _run_script("scripts/migration/azure_blob_to_gcs.py", extra_args or [])


@app.command("azure-search-export", help="Export Azure Cognitive Search indexes.")
def azure_search_export(extra_args: Optional[list[str]] = typer.Argument(None)) -> None:
    _run_script("scripts/migration/azure_search_export.py", extra_args or [])


@app.command("azure-search-to-vertex", help="Transform Azure search exports into Vertex ingest payloads.")
def azure_search_to_vertex(extra_args: Optional[list[str]] = typer.Argument(None)) -> None:
    _run_script("scripts/migration/azure_search_to_vertex.py", extra_args or [])


@app.command("import-vertex-documents", help="Import transformed Vertex documents.")
def import_vertex_documents(extra_args: Optional[list[str]] = typer.Argument(None)) -> None:
    _run_script("scripts/migration/import_vertex_documents.py", extra_args or [])


if __name__ == "__main__":
    app()
