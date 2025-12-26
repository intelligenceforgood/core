"""Bootstrap command helpers for local and dev environments."""

from __future__ import annotations

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


__all__ = [
    "bootstrap_app",
    "dev_app",
    "local_app",
    "run_local",
    "run_dev",
]
