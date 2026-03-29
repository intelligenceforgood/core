"""Bootstrap command helpers for local and dev environments."""

from __future__ import annotations

from pathlib import Path

import typer

from .dev import dev_app, run_dev
from .local import local_app, run_local

bootstrap_app = typer.Typer(help="Bootstrap or reset environments (local sandbox, dev refresh).")
bootstrap_app.add_typer(local_app, name="local")
bootstrap_app.add_typer(dev_app, name="dev")


def _exit_from_return(code: int | None) -> None:
    """Honor integer return codes from invoked helpers."""

    if isinstance(code, int) and code != 0:
        raise typer.Exit(code)


@bootstrap_app.command("seed-sample", help="Enqueue the sample dossier plan into the local queue store.")
def bootstrap_seed_sample() -> None:
    from . import seed

    _exit_from_return(seed.seed_sample_dossier())


@bootstrap_app.command("build-golden-bundle", help="Build the consolidated golden data bundle from all sources.")
def build_golden_bundle(
    bundles_dir: Path = typer.Option(Path("data/bundles"), help="Root bundles directory."),
    output_dir: Path = typer.Option(Path("data/bundles/golden"), help="Output directory."),
    skip_ids_file: Path | None = typer.Option(None, "--skip-ids", help="File with case IDs to skip (one per line)."),
) -> None:
    from scripts.build_golden_bundle import build

    skip_ids: set[str] = set()
    if skip_ids_file and skip_ids_file.exists():
        skip_ids = {line.strip() for line in skip_ids_file.read_text().splitlines() if line.strip()}
        typer.echo(f"Loaded {len(skip_ids)} case IDs to skip.")

    build(bundles_dir, output_dir, skip_ids)


__all__ = [
    "bootstrap_app",
    "dev_app",
    "local_app",
    "run_local",
    "run_dev",
]
