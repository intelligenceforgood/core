"""Unified CLI entry point for Intelligence for Good.

Config precedence: settings.default.toml -> settings.local.toml -> env vars (I4G_* with double underscores for nesting) -> CLI flags.
Use ``--install-completion`` to enable shell tab completion (bash required; zsh/fish supported when available).
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer

from i4g.cli.admin import admin_app
from i4g.cli.azure import app as azure_app
from i4g.cli.bootstrap import bootstrap_app
from i4g.cli.data import data_app
from i4g.cli.extract import extract_app
from i4g.cli.ingest import ingest_app
from i4g.cli.jobs import jobs_app
from i4g.cli.reports import reports_app
from i4g.cli.search import search_app
from i4g.cli.settings import settings_app
from i4g.cli.smoke import smoke_app

try:
    from importlib.metadata import version

    VERSION = version("i4g")
except Exception:
    VERSION = "unknown"

APP_HELP = (
    "i4g command line for developers and operators. "
    "Config precedence: settings.default.toml -> settings.local.toml -> env vars (I4G_* with __) -> CLI flags. "
    "Use --install-completion to enable shell tab completion. "
    "Guardrails: bootstrap commands enforce I4G_ENV and require --force to target non-local/dev projects."
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

app = typer.Typer(add_completion=True, help=APP_HELP)

app.add_typer(bootstrap_app, name="bootstrap")
app.add_typer(settings_app, name="settings")
app.add_typer(smoke_app, name="smoke")
app.add_typer(jobs_app, name="jobs")
app.add_typer(ingest_app, name="ingest")
app.add_typer(search_app, name="search")
app.add_typer(data_app, name="data")
app.add_typer(reports_app, name="reports")
app.add_typer(extract_app, name="extract")
app.add_typer(admin_app, name="admin")
app.add_typer(azure_app, name="azure")


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context, version: bool = typer.Option(False, "--version", help="Show version and exit.")) -> None:
    """Show help when no subcommand is provided."""

    if version:
        typer.echo(f"i4g {VERSION}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


if __name__ == "__main__":
    app()
