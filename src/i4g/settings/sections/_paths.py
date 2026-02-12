"""Shared project-root discovery used by settings section modules."""

from __future__ import annotations

import os
from pathlib import Path


def _env_project_root(var_name: str) -> Path | None:
    """Resolve an override path from the provided environment variable."""
    raw_value = os.getenv(var_name)
    if not raw_value:
        return None
    return Path(raw_value).expanduser().resolve()


def detect_project_root() -> Path:
    """Return the repository root, honoring environment overrides when set."""
    for env_var in ("I4G_PROJECT_ROOT", "I4G_RUNTIME__PROJECT_ROOT"):
        candidate = _env_project_root(env_var)
        if candidate:
            return candidate

    resolved = Path(__file__).resolve()
    for parent in resolved.parents:
        marker = parent / "pyproject.toml"
        if marker.exists() and (parent / "src").exists():
            return parent
    return resolved.parents[4]


PROJECT_ROOT = detect_project_root()

__all__ = ["PROJECT_ROOT", "detect_project_root"]
