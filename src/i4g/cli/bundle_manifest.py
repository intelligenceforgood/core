from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
HASH_CHUNK_SIZE = 8192
COUNTABLE_SUFFIXES = {".jsonl", ".json", ".yaml", ".yml", ".txt", ".csv"}


@dataclass
class FileRecord:
    path: str
    size_bytes: int
    sha256: str
    line_count: Optional[int] = None


@dataclass
class ManifestResult:
    manifest: Dict[str, Any]
    output_path: Path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def count_lines(path: Path) -> int:
    with path.open("rb") as handle:
        return sum(1 for _ in handle)


def summarize_file(path: Path, root: Path) -> FileRecord:
    size_bytes = path.stat().st_size
    sha256 = file_sha256(path)
    line_count: Optional[int] = None
    if path.suffix.lower() in COUNTABLE_SUFFIXES:
        line_count = count_lines(path)
    relative_path = path.relative_to(root).as_posix()
    return FileRecord(path=relative_path, size_bytes=size_bytes, sha256=sha256, line_count=line_count)


def build_manifest(
    bundle_dir: Path,
    bundle_id: str,
    provenance: Optional[str],
    license_name: Optional[str],
    tags: List[str],
    pii: bool,
    output_path: Path,
) -> ManifestResult:
    bundle_dir = bundle_dir.resolve()
    output_path = output_path.resolve()
    files: List[FileRecord] = []

    for path in sorted(bundle_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.resolve() == output_path:
            continue
        files.append(summarize_file(path, bundle_dir))

    total_bytes = sum(item.size_bytes for item in files)
    manifest = {
        "bundle_id": bundle_id,
        "root": str(bundle_dir),
        "generated_at": datetime.utcnow().strftime(ISO_FORMAT),
        "provenance": provenance or "",
        "license": license_name or "",
        "pii": bool(pii),
        "tags": tags,
        "totals": {"files": len(files), "bytes": total_bytes},
        "files": [record.__dict__ for record in files],
    }

    output_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return ManifestResult(manifest=manifest, output_path=output_path)


__all__ = ["build_manifest", "ManifestResult"]
