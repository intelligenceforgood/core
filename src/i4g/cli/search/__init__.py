"""Search command group."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import typer

from i4g.cli.search import logic
from i4g.settings import get_settings

search_app = typer.Typer(help="Search/retrieval queries and evaluations.")


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
    logic.query_vertex(
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
    exit_code = logic.evaluate_vertex(
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
    logic.refresh_hybrid_schema_snapshot(
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

    from i4g.cli.admin import helpers as saved_searches

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
