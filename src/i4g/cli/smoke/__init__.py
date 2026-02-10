import os
from typing import Optional

import typer

from . import runner as smoke

smoke_app = typer.Typer(help="Run smoketests against local or remote services.")


@smoke_app.command("dossiers", help="Verify dossier artifacts and signature manifests via API.")
def smoke_dossiers(
    api_url: str = typer.Option("http://localhost:8000", "--api-url", help="FastAPI base URL."),
    token: Optional[str] = typer.Option(None, "--token", help="API key for authenticated endpoints."),
    status: str = typer.Option("completed", "--status", help="Queue status filter."),
    limit: int = typer.Option(10, "--limit", help="Max dossiers to inspect."),
    plan_id: Optional[str] = typer.Option(None, "--plan-id", help="Specific dossier plan_id to verify."),
) -> None:
    """Run dossier smoke verification and hash checks."""

    from scripts import smoke_dossiers as smoke_script

    try:
        result = smoke_script.run_smoke(api_url=api_url, token=token, status=status, limit=limit, plan_id=plan_id)
    except smoke_script.SmokeError as exc:  # type: ignore[attr-defined]
        typer.echo(f"SMOKE FAILED: {exc}", err=True)
        raise typer.Exit(code=1)
    typer.echo(
        "SMOKE OK: plan=%s verified, manifest=%s, signature=%s"
        % (result.plan_id, result.manifest_path or "<none>", result.signature_path or "<none>")
    )


@smoke_app.command("vertex-search", help="Run vertex retrieval smoke script.")
def smoke_vertex_search(extra_args: Optional[list[str]] = typer.Argument(None)) -> None:
    """Run Vertex smoke: dry-run ingest then query."""

    project: str | None = None
    location: str = "global"
    data_store_id: str | None = None
    jsonl: str = "data/retrieval_poc/cases.jsonl"
    serving_config_id: str = "default_search"
    query: str = "wallet address verification"
    page_size: int = 5

    if extra_args:
        # Preserve backward compat: allow positional overrides similar to old script flags.
        # Expected order: project location data_store_id jsonl serving_config_id query page_size
        for idx, value in enumerate(extra_args):
            if idx == 0:
                project = value
            elif idx == 1:
                location = value
            elif idx == 2:
                data_store_id = value
            elif idx == 3:
                jsonl = value
            elif idx == 4:
                serving_config_id = value
            elif idx == 5:
                query = value
            elif idx == 6:
                page_size = int(value)

    if not project or not data_store_id:
        typer.echo("--project and --data-store-id are required (or pass as positional overrides).", err=True)
        raise typer.Exit(code=1)

    smoke.vertex_search_smoke(
        project=project,
        location=location,
        data_store_id=data_store_id,
        jsonl=jsonl,
        serving_config_id=serving_config_id,
        query=query,
        page_size=page_size,
    )


@smoke_app.command("cloud-run", help="Run Cloud Run smoke script.")
def smoke_cloud_run(extra_args: Optional[list[str]] = typer.Argument(None)) -> None:
    """Run the dev Cloud Run intake smoke end-to-end."""

    api_url: str | None = None
    token: str | None = None
    project: str | None = None
    region: str | None = None
    job: str | None = None
    container: str | None = None

    if extra_args:
        for idx, value in enumerate(extra_args):
            if idx == 0:
                api_url = value
            elif idx == 1:
                token = value
            elif idx == 2:
                project = value
            elif idx == 3:
                region = value
            elif idx == 4:
                job = value
            elif idx == 5:
                container = value

    # Defaults preserved from the original script env fallbacks.
    resolved_api_url = (
        api_url or os.getenv("I4G_SMOKE_API_URL") or "https://fastapi-gateway-y5jge5w2cq-uc.a.run.app"
    ).rstrip("/")
    resolved_token = token or os.getenv("I4G_SMOKE_TOKEN") or "dev-analyst-token"
    resolved_project = project or os.getenv("I4G_SMOKE_PROJECT") or "i4g-dev"
    resolved_region = region or os.getenv("I4G_SMOKE_REGION") or "us-central1"
    resolved_job = job or os.getenv("I4G_SMOKE_JOB") or "process-intakes"
    resolved_container = container or os.getenv("I4G_SMOKE_CONTAINER") or "container-0"

    smoke.cloud_run_smoke(
        api_url=resolved_api_url,
        token=resolved_token,
        project=resolved_project,
        region=resolved_region,
        job=resolved_job,
        container=resolved_container,
    )
