"""Local ingestion logic for dev bootstrap (runs locally instead of Cloud Run)."""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path

from i4g.cli.bootstrap.common import download_bundles as common_download_bundles, get_bundles
from i4g.cli.utils import stage_bundle

from .constants import BUNDLES_DIR, JobResult


def run_local_ingest(args: argparse.Namespace) -> list[JobResult]:
    """Run ingestion logic locally instead of via Cloud Run jobs."""
    results: list[JobResult] = []

    bundles_to_process: list[str] = []

    # 1. Determine bundles
    if args.bundle:
        all_bundles = get_bundles()
        if args.bundle not in all_bundles:
            logging.error("Bundle '%s' not found. Available: %s", args.bundle, list(all_bundles.keys()))
            return []
        uri = all_bundles[args.bundle]
        if uri.startswith("gs://"):
            try:
                local_bundle_path = stage_bundle(uri, BUNDLES_DIR)
                logging.info("Staged bundle '%s' to %s", args.bundle, local_bundle_path)
                bundles_to_process.append(str(local_bundle_path))
            except Exception as exc:
                logging.error("Failed to stage bundle: %s", exc)
                return []
        else:
            bundles_to_process.append(uri)
    elif args.bundle_uri:
        if args.bundle_uri.startswith("gs://"):
            logging.info("Using GCS URI directly for local execution: %s", args.bundle_uri)
            bundles_to_process.append(args.bundle_uri)
        else:
            try:
                local_bundle_path = stage_bundle(args.bundle_uri, BUNDLES_DIR)
                logging.info("Staged bundle to %s", local_bundle_path)
                bundles_to_process.append(str(local_bundle_path))
            except Exception as exc:
                logging.error("Failed to stage bundle: %s", exc)
                return [
                    JobResult(
                        label="bundle_stage",
                        job_name="local-bundle-stage",
                        command=f"stage_bundle({args.bundle_uri})",
                        status="failure",
                        stdout="",
                        stderr=str(exc),
                        error=str(exc),
                    )
                ]
    else:
        common_download_bundles(BUNDLES_DIR)
        bundles_to_process = [str(p) for p in sorted(BUNDLES_DIR.glob("**/*.jsonl"))]
        if not bundles_to_process:
            logging.warning("No bundles found in %s", BUNDLES_DIR)

    # 2. Run Ingest for each bundle
    requested_jobs: set[str] = set()
    if not args.skip_vertex:
        requested_jobs.add("vertex")
    if not args.skip_sql:
        requested_jobs.add("sql")
    if not args.skip_bigquery:
        requested_jobs.add("bigquery")

    if not requested_jobs:
        return results

    logging.info("Running local ingestion for: %s on %d bundles", requested_jobs, len(bundles_to_process))

    for bundle_path in bundles_to_process:
        logging.info("Processing bundle: %s", bundle_path)

        env = os.environ.copy()
        env["I4G_ENV"] = "dev"
        env["I4G_INGEST__JSONL_PATH"] = bundle_path

        if args.dataset:
            env["I4G_INGEST__DATASET_NAME"] = args.dataset
        if args.limit > 0:
            env["I4G_INGEST__BATCH_LIMIT"] = str(args.limit)
        if args.rate_limit_delay > 0:
            env["I4G_INGEST__RATE_LIMIT_DELAY"] = str(args.rate_limit_delay)
        if args.ingest_dry_run:
            env["I4G_INGEST__DRY_RUN"] = "1"

        env["I4G_INGEST__ENABLE_VERTEX"] = "1" if "vertex" in requested_jobs else "0"
        env["I4G_INGEST__ENABLE_VECTOR"] = "1" if "vertex" in requested_jobs else "0"

        if "vertex" in requested_jobs:
            if args.search_project:
                env["I4G_VERTEX_SEARCH_PROJECT"] = args.search_project
            if args.search_location:
                env["I4G_VERTEX_SEARCH_LOCATION"] = args.search_location
            if args.search_data_store_id:
                env["I4G_VERTEX_SEARCH_DATA_STORE"] = args.search_data_store_id
            elif not os.getenv("I4G_VERTEX_SEARCH_DATA_STORE"):
                env["I4G_VERTEX_SEARCH_DATA_STORE"] = "retrieval-poc"

        if args.dry_run:
            env["I4G_INGEST__DRY_RUN"] = "1"

        cmd = [sys.executable, "-m", "i4g.worker.jobs.ingest"]
        command_str = " ".join(cmd) + f" (bundle={bundle_path})"

        try:
            if args.dry_run:
                logging.info("[dry-run] Would run: %s", command_str)
                results.append(JobResult("ingest", "local-ingest", command_str, "skipped", "<dry-run>", "", None))
            else:
                proc = subprocess.run(cmd, env=env, capture_output=True, text=True, check=True)
                results.append(
                    JobResult("ingest", "local-ingest", command_str, "success", proc.stdout, proc.stderr, None)
                )
        except subprocess.CalledProcessError as exc:
            logging.error("Local ingestion failed for %s: %s", bundle_path, exc.stderr)
            results.append(
                JobResult("ingest", "local-ingest", command_str, "failure", exc.stdout, exc.stderr, str(exc))
            )

    # 3. Run Reports
    if not args.skip_reports:
        logging.info("Running local reports generation...")
        env = os.environ.copy()
        env["I4G_ENV"] = "dev"

        cmd = [sys.executable, "-m", "i4g.worker.jobs.report"]
        command_str = " ".join(cmd)

        try:
            if args.dry_run:
                logging.info("[dry-run] Would run: %s", command_str)
                results.append(JobResult("reports", "local-reports", command_str, "skipped", "<dry-run>", "", None))
            else:
                proc = subprocess.run(cmd, env=env, capture_output=True, text=True, check=True)
                results.append(
                    JobResult("reports", "local-reports", command_str, "success", proc.stdout, proc.stderr, None)
                )
        except subprocess.CalledProcessError as exc:
            logging.error("Local reports failed: %s", exc.stderr)
            results.append(
                JobResult("reports", "local-reports", command_str, "failure", exc.stdout, exc.stderr, str(exc))
            )

    # 4. Run Seed Reviews
    if args.seed_reviews_job:
        logging.info("Running local seed reviews...")
        env = os.environ.copy()
        env["I4G_ENV"] = "dev"

        cmd = ["i4g", "admin", "seed-reviews"]
        command_str = " ".join(cmd)

        try:
            if args.dry_run:
                logging.info("[dry-run] Would run: %s", command_str)
                results.append(
                    JobResult("seed_reviews", "local-seed-reviews", command_str, "skipped", "<dry-run>", "", None)
                )
            else:
                proc = subprocess.run(cmd, env=env, capture_output=True, text=True, check=True)
                results.append(
                    JobResult(
                        "seed_reviews", "local-seed-reviews", command_str, "success", proc.stdout, proc.stderr, None
                    )
                )
        except subprocess.CalledProcessError as exc:
            logging.error("Local seed reviews failed: %s", exc.stderr)
            results.append(
                JobResult(
                    "seed_reviews", "local-seed-reviews", command_str, "failure", exc.stdout, exc.stderr, str(exc)
                )
            )

    return results
