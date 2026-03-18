"""Cloud Run job specification building and execution."""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Any

import google.auth
import google.auth.impersonated_credentials
import google.auth.transport.requests
from googleapiclient.discovery import build

from i4g.cli.bootstrap.common import get_bundles

from .constants import JobResult, JobSpec
from .utils import format_command


def build_job_specs(args: argparse.Namespace) -> list[JobSpec]:
    """Build the list of Cloud Run job specs from CLI arguments."""

    # Determine bundles
    bundles_to_process: list[str] = []
    if args.bundle:
        all_bundles = get_bundles()
        if args.bundle not in all_bundles:
            logging.error("Bundle '%s' not found. Available: %s", args.bundle, list(all_bundles.keys()))
            return []
        bundles_to_process.append(all_bundles[args.bundle])
    elif args.bundle_uri:
        bundles_to_process.append(args.bundle_uri)
    else:
        all_bundles = get_bundles()
        for name, uri in all_bundles.items():
            if args.skip_ocr and name == "ocr_test_images":
                continue
            bundles_to_process.append(uri)

    specs: list[JobSpec] = []

    common_env: dict[str, str] = {}

    if "dev" in args.project or "prod" in args.project:
        common_env["I4G_STORAGE__STRUCTURED_BACKEND"] = "cloudsql"

        if "dev" in args.project:
            common_env["I4G_APP__CLOUDSQL__INSTANCE"] = f"{args.project}:us-central1:{args.project}-db"
            common_env["I4G_APP__CLOUDSQL__DATABASE"] = "i4g_db"
            common_env["I4G_APP__CLOUDSQL__USER"] = f"sa-ingest@{args.project}.iam"
            common_env["I4G_APP__CLOUDSQL__ENABLE_IAM_AUTH"] = "true"

            common_env["I4G_INGEST__ENABLE_VERTEX"] = "false"
            common_env["I4G_INGEST__ENABLE_VECTOR"] = "true"
            common_env["I4G_VECTOR__BACKEND"] = "vertex_ai"

            common_env["I4G_VERTEX_SEARCH_PROJECT"] = args.project
            common_env["I4G_VERTEX_SEARCH_LOCATION"] = args.region
            common_env["I4G_VERTEX_SEARCH_DATA_STORE"] = "retrieval-poc"

            common_env["I4G_LLM__PROVIDER"] = "vertex_ai"
            common_env["I4G_LLM__VERTEX_AI_PROJECT"] = args.project
            common_env["I4G_LLM__VERTEX_AI_LOCATION"] = args.region
            common_env["I4G_LLM__CHAT_MODEL"] = "gemini-2.5-flash"

    # Ingestion jobs (run per bundle)
    for bundle_uri in bundles_to_process:
        bundle_name = Path(bundle_uri).name

        ingest_env: dict[str, str] = common_env.copy()
        ingest_env["I4G_INGEST__JSONL_PATH"] = bundle_uri
        if args.dataset:
            ingest_env["I4G_INGEST__DATASET_NAME"] = args.dataset
        if args.limit > 0:
            ingest_env["I4G_INGEST__BATCH_LIMIT"] = str(args.limit)
        if args.rate_limit_delay > 0:
            ingest_env["I4G_INGEST__RATE_LIMIT_DELAY"] = str(args.rate_limit_delay)
        if args.ingest_dry_run:
            ingest_env["I4G_INGEST__DRY_RUN"] = "1"

        ingest_env["I4G_INGEST__SKIP_CLASSIFICATION"] = "1"

        job_args: list[str] = ["jobs", "ingest"]
        job_args.append(f"--bundle-uri={bundle_uri}")
        if args.dataset:
            job_args.append(f"--dataset={args.dataset}")

        if not args.skip_ingest and args.ingest_job:
            specs.append(
                JobSpec(label=f"ingest-{bundle_name}", job_name=args.ingest_job, args=job_args, env=ingest_env)
            )

        if not args.skip_vertex and args.vertex_job:
            specs.append(
                JobSpec(label=f"vertex-{bundle_name}", job_name=args.vertex_job, args=job_args, env=ingest_env)
            )
        if not args.skip_sql and args.sql_job:
            specs.append(JobSpec(label=f"sql-{bundle_name}", job_name=args.sql_job, args=job_args, env=common_env))
        if not args.skip_bigquery and args.bigquery_job:
            specs.append(
                JobSpec(label=f"bigquery-{bundle_name}", job_name=args.bigquery_job, args=job_args, env=common_env)
            )

    # One-time jobs (run once)
    common_args: list[str] = []
    if args.dataset:
        common_args.append(f"--dataset={args.dataset}")

    if not args.skip_gcs_assets and args.gcs_assets_job:
        specs.append(JobSpec(label="gcs_assets", job_name=args.gcs_assets_job, args=common_args, env=common_env))
    if not args.skip_reports and args.reports_job:
        report_env = common_env.copy()
        if "dev" in args.project:
            report_env["I4G_APP__CLOUDSQL__USER"] = f"sa-report@{args.project}.iam"
        specs.append(JobSpec(label="reports", job_name=args.reports_job, args=common_args, env=report_env))

    if args.seed_reviews_job and not args.skip_seed_reviews:
        seed_env = common_env.copy()

        specs.append(
            JobSpec(
                label="seed_campaigns",
                job_name=args.seed_reviews_job,
                args=["admin", "seed-campaigns"],
                env=seed_env,
            )
        )
        specs.append(
            JobSpec(
                label="seed_reviews",
                job_name=args.seed_reviews_job,
                args=["admin", "seed-reviews", "--include-static", "--reset"],
                env=seed_env,
            )
        )

    if not args.skip_saved_searches and args.saved_searches_job:
        specs.append(
            JobSpec(label="saved_searches", job_name=args.saved_searches_job, args=common_args, env=common_env)
        )

    return specs


def execute_job(spec: JobSpec, args: argparse.Namespace) -> JobResult:
    """Execute a Cloud Run job using the Google API Client (bypassing gcloud)."""

    cmd_display: list[str] = [
        "gcloud",
        "run",
        "jobs",
        "execute",
        spec.job_name,
        "--project",
        args.project,
        "--region",
        args.region,
        "--impersonate-service-account",
        args.wif_service_account,
        "--wait",
    ]
    if spec.args:
        cmd_display.append(f"--args={','.join(spec.args)}")
    if spec.env:
        env_pairs = [f"{k}={v}" for k, v in spec.env.items()]
        cmd_display.append(f"--update-env-vars={','.join(env_pairs)}")

    command_str = format_command(cmd_display, redacted_flags={"--impersonate-service-account"})
    logging.info("Executing (API): %s", command_str)

    if args.dry_run:
        logging.info("Dry-run enabled; command not executed.")
        return JobResult(
            label=spec.label,
            job_name=spec.job_name,
            command=command_str,
            status="skipped",
            stdout="<dry-run>",
            stderr="",
            error=None,
        )

    try:
        # 1. Authenticate
        creds, _ = google.auth.default()
        if args.wif_service_account:
            request = google.auth.transport.requests.Request()
            creds = google.auth.impersonated_credentials.Credentials(
                source_credentials=creds,
                target_principal=args.wif_service_account,
                target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
                lifetime=3600,
            )
            creds.refresh(request)

        # 2. Build Client
        service = build("run", "v2", credentials=creds, cache_discovery=False)
        parent = f"projects/{args.project}/locations/{args.region}/jobs/{spec.job_name}"

        # 3. Run Job
        overrides: dict[str, Any] = {}
        if args.timeout:
            overrides["timeout"] = args.timeout

        container_override: dict[str, Any] = {}
        if spec.args:
            container_override["args"] = spec.args
        if spec.env:
            container_override["env"] = [{"name": k, "value": v} for k, v in spec.env.items()]

        if container_override:
            overrides["containerOverrides"] = [container_override]

        logging.info("=== Cloud Run Job Trigger ===")
        logging.info("Job: %s", spec.job_name)
        if spec.env:
            logging.info("Environment Overrides:")
            for k, v in spec.env.items():
                logging.info("  %s=%s", k, v)

        logging.info("Triggering job %s...", spec.job_name)
        request = service.projects().locations().jobs().run(name=parent, body={"overrides": overrides})
        operation = request.execute()
        op_name = operation["name"]
        logging.info("Job started. Operation: %s", op_name)

        # 4. Poll for completion
        while not operation.get("done"):
            time.sleep(5)
            operation = service.projects().locations().operations().get(name=op_name).execute()

        # 5. Check status
        if "error" in operation:
            error_msg = json.dumps(operation["error"])
            logging.error("Job failed: %s", error_msg)
            return JobResult(
                label=spec.label,
                job_name=spec.job_name,
                command=command_str,
                status="failure",
                stdout=json.dumps(operation, indent=2),
                stderr=error_msg,
                error=error_msg,
            )

        logging.info("Job %s completed successfully.", spec.job_name)
        return JobResult(
            label=spec.label,
            job_name=spec.job_name,
            command=command_str,
            status="success",
            stdout=json.dumps(operation, indent=2),
            stderr="",
            error=None,
        )

    except Exception as exc:
        logging.error("Job execution failed: %s", exc)
        return JobResult(
            label=spec.label,
            job_name=spec.job_name,
            command=command_str,
            status="failure",
            stdout="",
            stderr=str(exc),
            error=str(exc),
        )
