"""Shared CLI utilities and console wiring."""

from __future__ import annotations

import os
import warnings

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

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


def hash_file(path: Path) -> str:
    """Compute SHA256 hash of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stage_bundle(bundle_uri: str | None, bundles_dir: Path) -> Path | None:
    """Place a provided bundle JSONL into data/bundles; supports gs:// and local paths."""

    if not bundle_uri:
        return None

    bundle_path: Path
    if bundle_uri.startswith("gs://"):
        bundle_name = bundle_uri.rstrip("/ ").split("/")[-1]
        bundle_path = bundles_dir / bundle_name
        bundles_dir.mkdir(parents=True, exist_ok=True)
        try:
            cmd = ["gsutil", "cp"]
            if bundle_uri.endswith("/"):
                cmd.append("-r")
            cmd.extend([bundle_uri, str(bundles_dir)])
            subprocess.run(cmd, check=True)
            # If we copied a directory, bundle_path should point to it
            # gsutil cp -r gs://.../dir data/bundles/ -> data/bundles/dir
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"Failed to download bundle from {bundle_uri}") from exc
    else:
        bundle_path = Path(bundle_uri)

    if not bundle_path.exists():
        raise RuntimeError(f"bundle-uri path not found: {bundle_uri}")

    if bundle_path.is_dir():
        jsonls = list(bundle_path.rglob("*.jsonl"))
        if not jsonls:
            raise RuntimeError(f"No JSONL files found in bundle-uri directory: {bundle_uri}")
        target = bundles_dir / jsonls[0].name
        target.write_bytes(jsonls[0].read_bytes())
        return target

    return bundle_path


__all__ = ["console", "SETTINGS", "iter_jsonl", "write_jsonl", "hash_file", "stage_bundle"]
