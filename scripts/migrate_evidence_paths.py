"""Migrate evidence artifacts from flat paths to sharded layout.

For each ``site_scans`` row with ``evidence_path`` set:

1. Compute new sharded path using ``evidence_path(scan_id)``.
2. Move/copy files from old path to new path.
3. Update ``site_scans.evidence_path`` in the database.

Supports both local filesystem and GCS backends.  The script is
idempotent — scans whose ``evidence_path`` already matches the
sharded pattern are skipped.

Usage::

    conda run -n i4g python scripts/migrate_evidence_paths.py [--dry-run] [--backend local|gcs]

When ``--backend`` is omitted the script auto-detects the backend from
the active ``I4G_ENV`` settings (``storage.ssi_evidence_backend`` or
``evidence.storage_backend``).  Pass it explicitly to override.
"""

from __future__ import annotations

import argparse
import logging
import re
import shutil
import sys
from pathlib import Path

import sqlalchemy as sa

from i4g.settings import get_settings
from i4g.store.sql import session_factory, site_scans
from i4g.utils.evidence_path import evidence_path as sharded_evidence_path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BATCH_SIZE = 50

# Matches the sharded pattern: .../scans/xx/yy/uuid-with-dashes/...
_SHARDED_PATTERN = re.compile(r"scans/[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f\-]{36}")


def _is_already_sharded(path: str) -> bool:
    """Return True if the path already uses the sharded layout."""
    return bool(_SHARDED_PATTERN.search(path))


def _migrate_local(
    rows: list[dict],
    *,
    settings: object,
    dry_run: bool,
) -> tuple[int, int, int]:
    """Migrate evidence directories on the local filesystem.

    Args:
        rows: List of dicts with ``scan_id`` and ``evidence_path``.
        settings: Application settings.
        dry_run: If True, log operations without performing them.

    Returns:
        Tuple of (migrated, skipped, errored) counts.
    """
    data_dir = Path(getattr(settings, "data_dir", "data"))
    evidence_base = data_dir / "evidence"

    migrated = 0
    skipped = 0
    errored = 0
    factory = session_factory()

    for row in rows:
        scan_id = str(row["scan_id"])
        old_path_str = str(row["evidence_path"])

        if _is_already_sharded(old_path_str):
            skipped += 1
            continue

        old_path = Path(old_path_str)
        if not old_path.is_absolute():
            old_path = evidence_base / old_path_str

        new_relative = sharded_evidence_path(scan_id)
        new_path = evidence_base / new_relative

        if not old_path.exists():
            logger.debug("Source path does not exist (already moved?): %s", old_path)
            skipped += 1
            continue

        if dry_run:
            logger.info("[DRY-RUN] Would move %s → %s", old_path, new_path)
            migrated += 1
            continue

        try:
            new_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old_path), str(new_path))
            # Update DB
            with factory() as session:
                session.execute(
                    sa.update(site_scans).where(site_scans.c.scan_id == scan_id).values(evidence_path=str(new_path))
                )
                session.commit()
            migrated += 1
        except Exception as exc:
            logger.error("Failed to migrate %s → %s: %s", old_path, new_path, exc)
            errored += 1

    return migrated, skipped, errored


def _migrate_gcs(
    rows: list[dict],
    *,
    settings: object,
    dry_run: bool,
) -> tuple[int, int, int]:
    """Migrate evidence blobs in Google Cloud Storage.

    Copies blobs from the old flat prefix to the sharded prefix, updates
    the DB, then deletes the old blobs after verification.

    Args:
        rows: List of dicts with ``scan_id`` and ``evidence_path``.
        settings: Application settings.
        dry_run: If True, log operations without performing them.

    Returns:
        Tuple of (migrated, skipped, errored) counts.
    """
    try:
        from google.cloud.storage import Client
    except ImportError:
        logger.error("google-cloud-storage is required for GCS migration")
        return 0, 0, len(rows)

    client = Client()
    bucket_name = settings.storage.ssi_evidence_bucket
    prefix = settings.storage.ssi_evidence_prefix.rstrip("/")

    if not bucket_name:
        logger.error("storage.ssi_evidence_bucket is not configured")
        return 0, 0, len(rows)

    bucket = client.bucket(bucket_name)
    factory = session_factory()

    migrated = 0
    skipped = 0
    errored = 0

    for row in rows:
        scan_id = str(row["scan_id"])
        old_path_str = str(row["evidence_path"])

        if _is_already_sharded(old_path_str):
            skipped += 1
            continue

        new_relative = sharded_evidence_path(scan_id)

        # Determine old and new GCS prefixes
        if old_path_str.startswith("gs://"):
            _, old_blob_prefix = old_path_str.replace("gs://", "").split("/", 1)
        else:
            old_blob_prefix = f"{prefix}/{scan_id}"

        new_blob_prefix = f"{prefix}/{new_relative}"

        try:
            # List blobs at old prefix
            old_blobs = list(bucket.list_blobs(prefix=old_blob_prefix + "/"))

            # Check whether blobs already exist at the new sharded prefix.
            # This handles the case where upload_directory always wrote to
            # sharded paths but the DB recorded the flat path.
            new_blobs = list(bucket.list_blobs(prefix=new_blob_prefix + "/"))
            if new_blobs and not old_blobs:
                logger.info(
                    "Blobs already at sharded path (%d files) — updating DB only: %s",
                    len(new_blobs),
                    new_blob_prefix,
                )
                if not dry_run:
                    new_gcs_uri = f"gs://{bucket_name}/{new_blob_prefix}"
                    with factory() as session:
                        session.execute(
                            sa.update(site_scans)
                            .where(site_scans.c.scan_id == scan_id)
                            .values(evidence_path=new_gcs_uri)
                        )
                        session.commit()
                migrated += 1
                continue

            if not old_blobs:
                logger.debug("No blobs found at old prefix: %s", old_blob_prefix)
                skipped += 1
                continue

            if dry_run:
                logger.info("[DRY-RUN] Would move %d blobs: %s → %s", len(old_blobs), old_blob_prefix, new_blob_prefix)
                migrated += 1
                continue

            # Copy blobs to new prefix
            new_blob_names = []
            for blob in old_blobs:
                relative_name = blob.name[len(old_blob_prefix) :]
                new_name = f"{new_blob_prefix}{relative_name}"
                bucket.copy_blob(blob, bucket, new_name)
                new_blob_names.append(new_name)

            # Verify all copied blobs exist
            all_copied = all(bucket.blob(n).exists() for n in new_blob_names)
            if not all_copied:
                logger.error("Copy verification failed for scan %s; skipping delete", scan_id)
                errored += 1
                continue

            # Update DB
            new_gcs_uri = f"gs://{bucket_name}/{new_blob_prefix}"
            with factory() as session:
                session.execute(
                    sa.update(site_scans).where(site_scans.c.scan_id == scan_id).values(evidence_path=new_gcs_uri)
                )
                session.commit()

            # Delete old blobs
            for blob in old_blobs:
                blob.delete()

            migrated += 1
        except Exception as exc:
            logger.error("Failed to migrate GCS blobs for scan %s: %s", scan_id, exc)
            errored += 1

    return migrated, skipped, errored


def migrate(*, dry_run: bool = False, backend: str = "local") -> tuple[int, int, int]:
    """Run the evidence path migration.

    Args:
        dry_run: If True, report what would be moved without acting.
        backend: ``"local"`` or ``"gcs"``.

    Returns:
        Tuple of (migrated, skipped, errored) counts.
    """
    settings = get_settings()
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
        logger.info("Nothing to migrate")
        return 0, 0, 0

    if backend == "gcs":
        migrated, skipped, errored = _migrate_gcs(row_dicts, settings=settings, dry_run=dry_run)
    else:
        migrated, skipped, errored = _migrate_local(row_dicts, settings=settings, dry_run=dry_run)

    logger.info(
        "Migration complete: migrated=%d, skipped=%d, errored=%d (of %d total)",
        migrated,
        skipped,
        errored,
        total,
    )
    return migrated, skipped, errored


def _resolve_backend(explicit: str | None) -> str:
    """Resolve the storage backend from CLI arg or settings.

    When no explicit backend is given, reads the active environment's
    evidence storage config.  Accepts ``local`` or ``gcs``.

    Args:
        explicit: Value passed via ``--backend``, or *None* for auto-detect.

    Returns:
        ``"local"`` or ``"gcs"``.
    """
    if explicit:
        return explicit
    settings = get_settings()
    backend = getattr(getattr(settings, "storage", None), "ssi_evidence_backend", None)
    if not backend:
        backend = getattr(getattr(settings, "evidence", None), "storage_backend", None)
    if backend and backend.lower() == "gcs":
        return "gcs"
    return "local"


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Migrate evidence artifacts to sharded layout")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be moved without acting")
    parser.add_argument(
        "--backend",
        choices=["local", "gcs"],
        default=None,
        help="Storage backend (default: auto-detect from I4G_ENV settings)",
    )
    args = parser.parse_args()

    backend = _resolve_backend(args.backend)
    logger.info("Using storage backend: %s", backend)
    _migrated, _skipped, errored = migrate(dry_run=args.dry_run, backend=backend)
    sys.exit(1 if errored > 0 else 0)


if __name__ == "__main__":
    main()
