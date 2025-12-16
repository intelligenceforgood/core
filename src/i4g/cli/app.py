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
)
from i4g.settings import get_settings

VERSION = (Path(__file__).resolve().parents[3] / "VERSION.txt").read_text().strip()

APP_HELP = (
    "i4g command line for developers and operators. "
    "Config precedence: settings.default.toml -> settings.local.toml -> env vars (I4G_* with __) -> CLI flags. "
    "Use --install-completion to enable shell tab completion."
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

app = typer.Typer(add_completion=True, help=APP_HELP)
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
app.add_typer(settings_app, name="settings")
app.add_typer(smoke_app, name="smoke")
app.add_typer(jobs_app, name="jobs")
app.add_typer(ingest_app, name="ingest")
app.add_typer(search_app, name="search")
app.add_typer(data_app, name="data")
app.add_typer(reports_app, name="reports")
app.add_typer(extract_app, name="extract")
app.add_typer(admin_app, name="admin")


def _exit_from_return(code: int | None) -> None:
    """Honor integer return codes from invoked helpers."""

    if isinstance(code, int) and code != 0:
        raise typer.Exit(code)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context, version: bool = typer.Option(False, "--version", help="Show version and exit.")) -> None:
    """Show help when no subcommand is provided."""

    if version:
        typer.echo(f"i4g {VERSION}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


@env_app.command("bootstrap-local", help="Refresh local sandbox data and artifacts.")
def env_bootstrap_local(
    skip_ocr: bool = typer.Option(False, "--skip-ocr", help="Skip generating chat screenshots and OCR."),
    skip_vector: bool = typer.Option(False, "--skip-vector", help="Skip rebuilding vector/structured stores."),
    reset: bool = typer.Option(False, "--reset", help="Delete derived artifacts before regenerating."),
) -> None:
    """Run the local sandbox bootstrap pipeline."""

    from scripts import bootstrap_local_sandbox

    argv: list[str] = []
    if skip_ocr:
        argv.append("--skip-ocr")
    if skip_vector:
        argv.append("--skip-vector")
    if reset:
        argv.append("--reset")
    bootstrap_local_sandbox.main(argv)


@env_app.command("seed-sample", help="Enqueue the sample dossier plan into the local queue store.")
def env_seed_sample() -> None:
    """Insert a sample dossier plan for quick smoke testing."""

    from scripts import enqueue_sample_dossier

    _exit_from_return(enqueue_sample_dossier.main())


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
