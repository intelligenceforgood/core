import typer
from pathlib import Path
from typing import Optional
from i4g.settings import get_settings

settings_app = typer.Typer(help="Inspect and export configuration manifests.")

PROJECT_ROOT = Path(__file__).resolve().parents[4]


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

    from . import manifest

    records = manifest.build_manifest()
    target_dir = manifest.ensure_directory(proto_docs_dir)
    manifest.write_json(records, target_dir)
    manifest.write_yaml(records, target_dir)
    manifest.write_markdown(records, target_dir)
    if docs_repo:
        manifest.write_docs_repo(records, docs_repo)


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
