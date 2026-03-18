"""Utility helpers for the dev bootstrap workflow."""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Iterable, Sequence
from pathlib import Path

from i4g.cli.utils import hash_file
from i4g.settings import get_settings

from .constants import DEFAULT_PROJECT, DEFAULT_REGION


def configure_logging(level: str) -> None:
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), format="%(levelname)s %(message)s")


def guard_environment(project: str, force: bool) -> None:
    settings = get_settings()
    if project.endswith("prod") or project.endswith("-prod"):
        raise SystemExit("Refusing to target a prod project.")
    if project != DEFAULT_PROJECT and not force:
        raise SystemExit("Pass --force to target non-dev projects (never use for prod).")
    if settings.env not in ("dev", "local") and not force:
        raise SystemExit(f"I4G_ENV is {settings.env}; set I4G_ENV=dev or pass --force explicitly.")
    if force:
        logging.warning("Force enabled: project=%s env=%s (use only when confident)", project, settings.env)
    logging.info("Guardrails: project=%s region=%s I4G_ENV=%s", project, DEFAULT_REGION, settings.env)


def summarize_bundle(bundle_uri: str | None) -> tuple[str | None, str | None]:
    """Return bundle URI and sha256 if the URI points to a local file."""

    if not bundle_uri:
        return None, None

    candidate = Path(bundle_uri)
    if candidate.is_file():
        return str(candidate), hash_file(candidate)
    return bundle_uri, None


def format_command(cmd: Sequence[str], redacted_flags: Iterable[str] | None = None) -> str:
    redacted_flags = set(redacted_flags or [])
    rendered: list[str] = []
    for idx, token in enumerate(cmd):
        if token in redacted_flags:
            rendered.append(f"{token} <redacted>")
            continue
        if idx > 0 and cmd[idx - 1] in redacted_flags:
            rendered.append("<redacted>")
            continue
        rendered.append(token)
    return " ".join(rendered)


def run_command(cmd: Sequence[str], *, dry_run: bool) -> subprocess.CompletedProcess[str] | None:
    logging.info(
        "Executing: %s",
        format_command(cmd, redacted_flags={"--impersonate-service-account"}),
    )
    if dry_run:
        logging.info("Dry-run enabled; command not executed.")
        return None

    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:  # pragma: no cover - subprocess failure path
        stdout = (exc.stdout or "").strip()
        stderr = (exc.stderr or "").strip()
        if stdout:
            logging.error("Command stdout:\n%s", stdout)
        if stderr:
            logging.error("Command stderr:\n%s", stderr)
        raise
