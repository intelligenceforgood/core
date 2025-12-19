"""Admin command group."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import typer

from i4g.cli.admin import dossiers, pilot, saved_searches
from i4g.settings import get_settings

admin_app = typer.Typer(help="Saved search and dossier administration.")


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

    from i4g.cli.search import logic as search_logic

    settings = get_settings()
    search_logic.run_query(SimpleNamespace(question=question, backend=backend or settings.vector.backend))


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

    from i4g.cli.search import logic as search_logic

    settings = get_settings()
    search_logic.run_vertex_search(
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
