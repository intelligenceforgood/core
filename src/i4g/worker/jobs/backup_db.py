"""Backup database Cloud Run job.

Connects to Cloud SQL via cloud-sql-proxy, runs pg_dump, gzips the output,
and uploads to GCS at ``gs://i4g-{env}-data-bundles/backups/{timestamp}/dump.sql.gz``.
"""

from __future__ import annotations

import gzip
import logging
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def _wait_for_port(port: int, timeout: int = 60) -> None:
    """Block until a TCP port is accepting connections."""
    for _ in range(timeout):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            time.sleep(1)
    raise TimeoutError(f"Port {port} not ready after {timeout}s")


def main() -> int:
    """Run the database backup job."""
    from i4g.settings import get_settings

    settings = get_settings()
    env = settings.env or "dev"

    # Resolve Cloud SQL connection parameters from app settings.
    instance = settings.app.cloudsql.instance
    database = settings.app.cloudsql.database
    user = settings.app.cloudsql.user
    enable_iam = settings.app.cloudsql.enable_iam_auth

    if not instance or not database:
        logger.error("Cloud SQL instance/database not configured.")
        return 1

    proxy_port = 15432
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    gcs_bucket = f"i4g-{env}-data-bundles"
    gcs_path = f"backups/{ts}/dump.sql.gz"

    proxy_bin = shutil.which("cloud-sql-proxy")
    if not proxy_bin:
        logger.error("cloud-sql-proxy not found on PATH.")
        return 1

    pg_dump_bin = shutil.which("pg_dump")
    if not pg_dump_bin:
        logger.error("pg_dump not found on PATH.")
        return 1

    # Start cloud-sql-proxy with IAM authentication.
    proxy_args = [proxy_bin, f"{instance}?port={proxy_port}"]
    if enable_iam:
        proxy_args.append("--auto-iam-authn")
    logger.info("Starting cloud-sql-proxy: %s", " ".join(proxy_args))
    proxy = subprocess.Popen(proxy_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    try:
        _wait_for_port(proxy_port)
        logger.info("cloud-sql-proxy ready on port %d", proxy_port)

        # Run pg_dump.
        pg_dump_cmd = [
            pg_dump_bin,
            "-h",
            "127.0.0.1",
            "-p",
            str(proxy_port),
            "-U",
            user,
            "-d",
            database,
            "--no-owner",
            "--no-acl",
        ]
        if enable_iam:
            pg_dump_cmd.append("--no-password")

        logger.info("Running pg_dump against %s/%s", instance, database)
        result = subprocess.run(pg_dump_cmd, capture_output=True)
        if result.returncode != 0:
            logger.error("pg_dump failed: %s", result.stderr.decode())
            return result.returncode

        # Gzip and write to temp file.
        with tempfile.NamedTemporaryFile(suffix=".sql.gz", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            with gzip.open(tmp_path, "wb") as gz:
                gz.write(result.stdout)

        size_mb = tmp_path.stat().st_size / (1024 * 1024)
        logger.info("Backup compressed: %.1f MB", size_mb)

        # Upload to GCS.
        try:
            from google.cloud import storage as gcs

            client = gcs.Client()
            bucket = client.bucket(gcs_bucket)
            blob = bucket.blob(gcs_path)
            blob.upload_from_filename(str(tmp_path))
            logger.info("Backup uploaded to gs://%s/%s", gcs_bucket, gcs_path)
        except Exception:
            logger.exception("GCS upload failed — backup saved locally at %s", tmp_path)
            return 1
        finally:
            tmp_path.unlink(missing_ok=True)

        return 0
    finally:
        proxy.send_signal(signal.SIGTERM)
        try:
            proxy.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proxy.kill()
        logger.info("cloud-sql-proxy stopped")
