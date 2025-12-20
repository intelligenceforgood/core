"""Shared CLI utilities and console wiring."""

from __future__ import annotations

import os
import warnings

import json
from pathlib import Path
from typing import Any, Iterable, Iterator

from rich.console import Console

from i4g.settings import get_settings

# Fix for OpenMP runtime conflict on macOS.
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

console = Console()
SETTINGS = get_settings()

# Quiet noisy third-party warnings during CLI invocations.
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """Yield dicts from a JSONL file."""
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


def write_jsonl(path: Path, data: Iterable[dict[str, Any]]) -> None:
    """Write dicts to a JSONL file."""
    with path.open("w", encoding="utf-8") as fh:
        for item in data:
            fh.write(json.dumps(item) + "\n")


__all__ = ["console", "SETTINGS", "iter_jsonl", "write_jsonl"]
