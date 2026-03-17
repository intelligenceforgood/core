"""Evidence manifest generation for SSI investigation artifacts."""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def generate_evidence_manifest(evidence_dir: Path, scan_id: str) -> dict[str, Any]:
    """Generate a manifest listing all artifacts with SHA-256 hashes.

    Args:
        evidence_dir: Local directory containing evidence files.
        scan_id: The scan identifier for this investigation.

    Returns:
        Manifest dict with file inventory and integrity hashes.
    """
    manifest: dict[str, Any] = {
        "scan_id": scan_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "files": [],
    }

    for file_path in sorted(evidence_dir.rglob("*")):
        if not file_path.is_file():
            continue
        sha256 = _compute_sha256(file_path)
        manifest["files"].append(
            {
                "path": str(file_path.relative_to(evidence_dir)),
                "size_bytes": file_path.stat().st_size,
                "sha256": sha256,
            }
        )

    return manifest


def _compute_sha256(file_path: Path) -> str:
    """Compute SHA-256 hex digest for a file.

    Args:
        file_path: Path to the file.

    Returns:
        Hex-encoded SHA-256 digest string.
    """
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
