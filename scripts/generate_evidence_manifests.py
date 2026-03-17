"""Generate metadata.json manifests for existing scan evidence directories.

For each ``site_scans`` row with an ``evidence_path``, lists all files in
the evidence directory, computes SHA-256 hashes, and writes a
``metadata.json`` manifest to the evidence directory.

Supports both local filesystem and GCS backends.

Usage::

    conda run -n i4g python scripts/generate_evidence_manifests.py [--dry-run] [--backend local|gcs]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa

from i4g.settings import get_settings
from i4g.store.sql import session_factory, site_scans

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _compute_sha256(file_path: Path) -> str:
    """Compute SHA-256 hex digest for a file.

    Args:
        file_path: Path to the file.

    Returns:
        Hex-encoded SHA-256 hash.
    """
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _generate_manifest_local(scan_id: str, evidence_dir: Path) -> dict:
    """Generate a manifest for a local evidence directory.

    Args:
        scan_id: The scan UUID.
        evidence_dir: Local path to the evidence directory.

    Returns:
        Manifest dict.
    """
    files = []
    for file_path in sorted(evidence_dir.rglob("*")):
        if file_path.is_file() and file_path.name != "metadata.json":
            files.append(
                {
                    "path": str(file_path.relative_to(evidence_dir)),
                    "size_bytes": file_path.stat().st_size,
                    "sha256": _compute_sha256(file_path),
                }
            )

    return {
        "scan_id": scan_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "file_count": len(files),
        "files": files,
    }


def _process_local(rows: list[dict], *, dry_run: bool) -> tuple[int, int, int]:
    """Generate manifests for local evidence directories.

    Args:
        rows: List of dicts with ``scan_id`` and ``evidence_path``.
        dry_run: If True, log what would be generated without writing.

    Returns:
        Tuple of (generated, skipped, errored) counts.
    """
    generated = 0
    skipped = 0
    errored = 0

    for row in rows:
        scan_id = str(row["scan_id"])
        evidence_path = str(row["evidence_path"])

        if evidence_path.startswith("gs://"):
            logger.debug("Skipping GCS path in local mode: %s", evidence_path)
            skipped += 1
            continue

        evidence_dir = Path(evidence_path)
        if not evidence_dir.exists():
            logger.debug("Evidence directory does not exist: %s", evidence_dir)
            skipped += 1
            continue

        manifest_path = evidence_dir / "metadata.json"
        if manifest_path.exists():
            logger.debug("Manifest already exists: %s", manifest_path)
            skipped += 1
            continue

        try:
            manifest = _generate_manifest_local(scan_id, evidence_dir)

            if dry_run:
                logger.info(
                    "[DRY-RUN] Would generate manifest for %s (%d files)",
                    scan_id,
                    manifest["file_count"],
                )
                generated += 1
                continue

            with open(manifest_path, "w") as f:
                json.dump(manifest, f, indent=2)
            logger.debug("Generated manifest for %s (%d files)", scan_id, manifest["file_count"])
            generated += 1
        except Exception as exc:
            logger.error("Failed to generate manifest for %s: %s", scan_id, exc)
            errored += 1

    return generated, skipped, errored


def _process_gcs(rows: list[dict], *, dry_run: bool) -> tuple[int, int, int]:
    """Generate manifests for GCS evidence directories.

    Args:
        rows: List of dicts with ``scan_id`` and ``evidence_path``.
        dry_run: If True, log what would be generated without writing.

    Returns:
        Tuple of (generated, skipped, errored) counts.
    """
    try:
        from google.cloud.storage import Client
    except ImportError:
        logger.error("google-cloud-storage is required for GCS manifest generation")
        return 0, 0, len(rows)

    settings = get_settings()
    client = Client()
    bucket_name = settings.storage.ssi_evidence_bucket

    if not bucket_name:
        logger.error("storage.ssi_evidence_bucket is not configured")
        return 0, 0, len(rows)

    bucket = client.bucket(bucket_name)
    generated = 0
    skipped = 0
    errored = 0

    for row in rows:
        scan_id = str(row["scan_id"])
        evidence_path = str(row["evidence_path"])

        # Parse the GCS prefix
        if evidence_path.startswith("gs://"):
            _, blob_prefix = evidence_path.replace("gs://", "").split("/", 1)
        else:
            skipped += 1
            continue

        blob_prefix = blob_prefix.rstrip("/")

        # Check if manifest already exists
        manifest_blob = bucket.blob(f"{blob_prefix}/metadata.json")
        if manifest_blob.exists():
            skipped += 1
            continue

        try:
            blobs = list(bucket.list_blobs(prefix=blob_prefix + "/"))
            files = []
            for blob in blobs:
                if blob.name.endswith("/") or blob.name.endswith("metadata.json"):
                    continue
                relative = blob.name[len(blob_prefix) + 1 :]
                # GCS provides md5 hash but not sha256; compute from blob content
                content = blob.download_as_bytes()
                sha256 = hashlib.sha256(content).hexdigest()
                files.append(
                    {
                        "path": relative,
                        "size_bytes": blob.size,
                        "sha256": sha256,
                    }
                )

            manifest = {
                "scan_id": scan_id,
                "generated_at": datetime.now(UTC).isoformat(),
                "file_count": len(files),
                "files": sorted(files, key=lambda f: f["path"]),
            }

            if dry_run:
                logger.info(
                    "[DRY-RUN] Would generate manifest for %s (%d files)",
                    scan_id,
                    manifest["file_count"],
                )
                generated += 1
                continue

            manifest_blob.upload_from_string(
                json.dumps(manifest, indent=2),
                content_type="application/json",
            )
            generated += 1
        except Exception as exc:
            logger.error("Failed to generate manifest for %s: %s", scan_id, exc)
            errored += 1

    return generated, skipped, errored


def generate_manifests(*, dry_run: bool = False, backend: str = "local") -> tuple[int, int, int]:
    """Generate evidence manifests for all scans.

    Args:
        dry_run: If True, report what would be generated without writing.
        backend: ``"local"`` or ``"gcs"``.

    Returns:
        Tuple of (generated, skipped, errored) counts.
    """
    factory = session_factory()

    with factory() as session:
        rows = session.execute(
            sa.select(site_scans.c.scan_id, site_scans.c.evidence_path).where(
                site_scans.c.evidence_path.isnot(None),
            )
        ).fetchall()

    row_dicts = [{"scan_id": r.scan_id, "evidence_path": r.evidence_path} for r in rows]
    total = len(row_dicts)
    logger.info("Found %d scans with evidence_path set", total)

    if not row_dicts:
        logger.info("Nothing to process")
        return 0, 0, 0

    if backend == "gcs":
        generated, skipped, errored = _process_gcs(row_dicts, dry_run=dry_run)
    else:
        generated, skipped, errored = _process_local(row_dicts, dry_run=dry_run)

    logger.info(
        "Manifest generation complete: generated=%d, skipped=%d, errored=%d (of %d total)",
        generated,
        skipped,
        errored,
        total,
    )
    return generated, skipped, errored


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Generate evidence manifests for existing scans")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be generated without writing")
    parser.add_argument(
        "--backend",
        choices=["local", "gcs"],
        default="local",
        help="Storage backend (default: local)",
    )
    args = parser.parse_args()

    _generated, _skipped, errored = generate_manifests(dry_run=args.dry_run, backend=args.backend)
    sys.exit(1 if errored > 0 else 0)


if __name__ == "__main__":
    main()
