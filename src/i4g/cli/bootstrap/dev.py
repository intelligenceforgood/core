"""Bootstrap helpers for the dev environment (Cloud Run jobs)."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable, List, Optional, Sequence

import typer

from i4g.settings import get_settings

REPO_ROOT = Path(__file__).resolve().parents[4]

DEFAULT_WIF_SA = "sa-infra@i4g-dev.iam.gserviceaccount.com"
DEFAULT_RUNTIME_SA = "sa-app@i4g-dev.iam.gserviceaccount.com"
IAP_CLIENT_ID_FALLBACK = "544936845045-a87u04lgc7go7asc4nhed36ka50iqh0h.apps.googleusercontent.com"
DEFAULT_PROJECT = "i4g-dev"
DEFAULT_REGION = "us-central1"
DEFAULT_REPORT_DIR = REPO_ROOT / "data" / "reports" / "dev_bootstrap"
DEFAULT_JOBS = {
    "firestore": "bootstrap-firestore",
    "vertex": "bootstrap-vertex",
    "sql": "bootstrap-sql",
    "bigquery": "bootstrap-bigquery",
    "gcs_assets": "bootstrap-gcs-assets",
    "reports": "bootstrap-reports",
    "saved_searches": "bootstrap-saved-searches",
}


@dataclass
class JobSpec:
    label: str
    job_name: str
    args: list[str]


@dataclass
class JobResult:
    label: str
    job_name: str
    command: str
    status: str
    stdout: str
    stderr: str
    error: str | None


@dataclass
class SmokeResult:
    status: str
    message: str


@dataclass
class DossierSmokeResult:
    status: str
    message: str
    plan_id: Optional[str]
    manifest_path: Optional[str]
    signature_path: Optional[str]


@dataclass
class SearchSmokeResult:
    status: str
    message: str


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap the dev environment via Cloud Run jobs")
    parser.add_argument("--project", default=DEFAULT_PROJECT, help="Target GCP project (default: i4g-dev).")
    parser.add_argument("--region", default=DEFAULT_REGION, help="Cloud Run region (default: us-central1).")
    parser.add_argument("--bundle-uri", dest="bundle_uri", help="Bundle URI passed to all jobs, if supported.")
    parser.add_argument("--dataset", help="Dataset identifier injected into job args, if supported.")
    parser.add_argument(
        "--wif-service-account",
        default=DEFAULT_WIF_SA,
        help="Service account to impersonate via WIF (default: sa-infra@i4g-dev).",
    )
    parser.add_argument("--firestore-job", default=DEFAULT_JOBS["firestore"], help="Firestore refresh job name.")
    parser.add_argument("--vertex-job", default=DEFAULT_JOBS["vertex"], help="Vertex import job name.")
    parser.add_argument("--sql-job", default=DEFAULT_JOBS["sql"], help="SQL/Firestore sync job name.")
    parser.add_argument("--bigquery-job", default=DEFAULT_JOBS["bigquery"], help="BigQuery refresh job name.")
    parser.add_argument("--gcs-assets-job", default=DEFAULT_JOBS["gcs_assets"], help="GCS asset sync job name.")
    parser.add_argument("--reports-job", default=DEFAULT_JOBS["reports"], help="Reports/dossiers job name.")
    parser.add_argument(
        "--saved-searches-job",
        default=DEFAULT_JOBS["saved_searches"],
        help="Saved searches/tag presets job name.",
    )
    parser.add_argument("--skip-firestore", action="store_true", help="Skip Firestore refresh job.")
    parser.add_argument("--skip-vertex", action="store_true", help="Skip Vertex import job.")
    parser.add_argument("--skip-sql", action="store_true", help="Skip SQL/Firestore sync job.")
    parser.add_argument("--skip-bigquery", action="store_true", help="Skip BigQuery refresh job.")
    parser.add_argument("--skip-gcs-assets", action="store_true", help="Skip GCS asset sync job.")
    parser.add_argument("--skip-reports", action="store_true", help="Skip reports/dossiers job.")
    parser.add_argument("--skip-saved-searches", action="store_true", help="Skip saved searches job.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned commands without executing them.")
    parser.add_argument(
        "--verify-only", action="store_true", help="Skip job execution and only run verification smokes."
    )
    parser.add_argument(
        "--run-smoke",
        action="store_true",
        help="Run Cloud Run intake smoke after job execution (or standalone with --verify-only).",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=DEFAULT_REPORT_DIR,
        help="Directory to write JSON/Markdown reports (default: data/reports/dev_bootstrap).",
    )
    parser.add_argument("--force", action="store_true", help="Allow targeting non-dev projects (never use for prod).")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO).",
    )
    parser.add_argument(
        "--smoke-api-url",
        default=os.getenv("I4G_SMOKE_API_URL", "https://api.intelligenceforgood.org"),
        help="API base URL for smoke (default: dev gateway).",
    )
    parser.add_argument(
        "--smoke-token",
        default=os.getenv("I4G_SMOKE_TOKEN", "dev-analyst-token"),
        help="API token for smoke requests.",
    )
    parser.add_argument(
        "--smoke-job",
        default=os.getenv("I4G_SMOKE_JOB", "process-intakes"),
        help="Cloud Run job to execute for intake smoke.",
    )
    parser.add_argument(
        "--smoke-container",
        default=os.getenv("I4G_SMOKE_CONTAINER", "container-0"),
        help="Container name for the smoke job.",
    )
    parser.add_argument("--run-dossier-smoke", action="store_true", help="Run dossier verification smoke via API.")
    parser.add_argument("--run-search-smoke", action="store_true", help="Run Vertex search smoke after bootstrap.")
    parser.add_argument("--search-project", help="Vertex project for search smoke (defaults to --project).")
    parser.add_argument(
        "--search-location", default="global", help="Vertex location for search smoke (default: global)."
    )
    parser.add_argument("--search-data-store-id", help="Vertex data store id for search smoke.")
    parser.add_argument(
        "--search-serving-config-id",
        default="default_search",
        help="Vertex serving config id for search smoke (default: default_search).",
    )
    parser.add_argument(
        "--search-query",
        default="wallet address verification",
        help="Query string to issue during search smoke.",
    )
    parser.add_argument("--search-page-size", type=int, default=5, help="Page size for search smoke results.")
    return parser.parse_args(argv)


def configure_logging(level: str) -> None:
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), format="%(levelname)s %(message)s")


def guard_environment(project: str, force: bool) -> None:
    settings = get_settings()
    if project.endswith("prod") or project.endswith("-prod"):
        raise SystemExit("Refusing to target a prod project.")
    if project != DEFAULT_PROJECT and not force:
        raise SystemExit("Pass --force to target non-dev projects (never use for prod).")
    if settings.env not in ("dev", "local") and not force:
        raise SystemExit(f"I4G_ENV is {settings.env}; set I4G_ENV=dev or pass --force explicitly.")
    if force:
        logging.warning("Force enabled: project=%s env=%s (use only when confident)", project, settings.env)
    logging.info("Guardrails: project=%s region=%s I4G_ENV=%s", project, DEFAULT_REGION, settings.env)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def summarize_bundle(bundle_uri: str | None) -> tuple[str | None, str | None]:
    """Return bundle URI and sha256 if the URI points to a local file."""

    if not bundle_uri:
        return None, None
    candidate = Path(bundle_uri)
    if candidate.is_file():
        return str(candidate), _file_sha256(candidate)
    return bundle_uri, None


def format_command(cmd: Sequence[str], redacted_flags: Iterable[str] | None = None) -> str:
    redacted_flags = set(redacted_flags or [])
    rendered: List[str] = []
    for idx, token in enumerate(cmd):
        if token in redacted_flags:
            rendered.append(f"{token} <redacted>")
            continue
        if idx > 0 and cmd[idx - 1] in redacted_flags:
            rendered.append("<redacted>")
            continue
        rendered.append(token)
    return " ".join(rendered)


def run_command(cmd: Sequence[str], *, dry_run: bool) -> subprocess.CompletedProcess[str] | None:
    logging.info(
        "Executing: %s",
        format_command(cmd, redacted_flags={"--impersonate-service-account"}),
    )
    if dry_run:
        logging.info("Dry-run enabled; command not executed.")
        return None

    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:  # pragma: no cover - subprocess failure path
        stdout = (exc.stdout or "").strip()
        stderr = (exc.stderr or "").strip()
        if stdout:
            logging.error("Command stdout:\n%s", stdout)
        if stderr:
            logging.error("Command stderr:\n%s", stderr)
        raise


def build_job_specs(args: argparse.Namespace) -> list[JobSpec]:
    common_args: list[str] = []
    if args.bundle_uri:
        common_args.append(f"--bundle-uri={args.bundle_uri}")
    if args.dataset:
        common_args.append(f"--dataset={args.dataset}")
    specs: list[JobSpec] = []
    if not args.skip_firestore and args.firestore_job:
        specs.append(JobSpec(label="firestore", job_name=args.firestore_job, args=common_args))
    if not args.skip_vertex and args.vertex_job:
        specs.append(JobSpec(label="vertex", job_name=args.vertex_job, args=common_args))
    if not args.skip_sql and args.sql_job:
        specs.append(JobSpec(label="sql", job_name=args.sql_job, args=common_args))
    if not args.skip_bigquery and args.bigquery_job:
        specs.append(JobSpec(label="bigquery", job_name=args.bigquery_job, args=common_args))
    if not args.skip_gcs_assets and args.gcs_assets_job:
        specs.append(JobSpec(label="gcs_assets", job_name=args.gcs_assets_job, args=common_args))
    if not args.skip_reports and args.reports_job:
        specs.append(JobSpec(label="reports", job_name=args.reports_job, args=common_args))
    if not args.skip_saved_searches and args.saved_searches_job:
        specs.append(JobSpec(label="saved_searches", job_name=args.saved_searches_job, args=common_args))
    return specs


def execute_job(spec: JobSpec, args: argparse.Namespace) -> JobResult:
    cmd: list[str] = [
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
        cmd.append(f"--args={','.join(spec.args)}")

    proc = run_command(cmd, dry_run=args.dry_run)
    stdout = proc.stdout.strip() if proc else "<dry-run>"
    stderr = proc.stderr.strip() if proc else ""
    return JobResult(
        label=spec.label,
        job_name=spec.job_name,
        command=format_command(cmd, redacted_flags={"--impersonate-service-account"}),
        status="success" if proc or args.dry_run else "skipped",
        stdout=stdout,
        stderr=stderr,
        error=None,
    )


def _get_iap_token(project: str, service_account: str | None) -> str | None:
    """Fetch an IAP-compatible ID token by looking up the backend service audience."""
    # Always use the runtime SA for IAP access as it has the correct permissions
    impersonate_sa = DEFAULT_RUNTIME_SA
    
    try:
        # 1. Fetch the IAP Client ID (audience) from the backend service
        # We assume the backend service name is 'i4g-lb-backend-api' as per Terraform
        cmd = [
            "gcloud",
            "compute",
            "backend-services",
            "describe",
            "i4g-lb-backend-api",
            "--project",
            project,
            "--global",
            "--format=value(iap.oauth2ClientId)",
            f"--impersonate-service-account={impersonate_sa}",
        ]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
            )
            audience = proc.stdout.strip()
        except subprocess.CalledProcessError:
            # Fallback to known Client ID if lookup fails (e.g. permissions)
            audience = IAP_CLIENT_ID_FALLBACK

        if not audience:
            return None

        # 2. Generate ID token with the audience and email claim
        cmd = [
            "gcloud",
            "auth",
            "print-identity-token",
            f"--audiences={audience}",
            "--include-email",
            f"--impersonate-service-account={impersonate_sa}",
        ]

        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return proc.stdout.strip()

    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        logging.debug("_get_iap_token failed: %s", exc)
        if isinstance(exc, subprocess.CalledProcessError):
            logging.debug("stderr: %s", exc.stderr)
        return None


def run_smoke(args: argparse.Namespace) -> SmokeResult:
    from i4g.cli import smoke

    iap_token = _get_iap_token(args.project, args.wif_service_account)

    smoke_args = SimpleNamespace(
        api_url=args.smoke_api_url,
        token=args.smoke_token,
        project=args.project,
        region=args.region,
        job=args.smoke_job,
        container=args.smoke_container,
        iap_token=iap_token,
    )
    try:
        smoke.cloud_run_smoke(smoke_args)
    except SystemExit as exc:  # pragma: no cover - subprocess failure path
        return SmokeResult(status="failed", message=str(exc))
    return SmokeResult(status="success", message="Cloud Run intake smoke passed")


def run_dossier_smoke(args: argparse.Namespace) -> DossierSmokeResult:
    from scripts import smoke_dossiers

    iap_token = _get_iap_token(args.project, args.wif_service_account)
    if not iap_token:
        try:
            proc = subprocess.run(
                ["gcloud", "auth", "print-identity-token"],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode == 0:
                iap_token = proc.stdout.strip()
        except Exception:
            pass

    smoke_args = SimpleNamespace(
        api_url=args.smoke_api_url,
        token=args.smoke_token,
        status="completed",
        limit=5,
        plan_id=None,
        iap_token=iap_token,
    )
    try:
        result = smoke_dossiers.run_smoke(smoke_args)
    except smoke_dossiers.SmokeError as exc:
        return DossierSmokeResult(
            status="failed",
            message=str(exc),
            plan_id=None,
            manifest_path=None,
            signature_path=None,
        )
    except Exception as exc:  # pragma: no cover - safety net
        return DossierSmokeResult(
            status="failed",
            message=str(exc),
            plan_id=None,
            manifest_path=None,
            signature_path=None,
        )

    return DossierSmokeResult(
        status="success",
        message="Dossier verification passed",
        plan_id=str(result.plan_id),
        manifest_path=str(result.manifest_path) if result.manifest_path else None,
        signature_path=str(result.signature_path) if result.signature_path else None,
    )


def run_search_smoke(args: argparse.Namespace) -> SearchSmokeResult:
    from i4g.cli import smoke

    if not args.search_project or not args.search_data_store_id or not args.search_serving_config_id:
        return SearchSmokeResult(
            status="skipped",
            message="Search smoke skipped; search project/data store/serving config not provided.",
        )

    search_args = SimpleNamespace(
        project=args.search_project,
        location=args.search_location or "global",
        data_store_id=args.search_data_store_id,
        serving_config_id=args.search_serving_config_id,
        query=args.search_query,
        page_size=args.search_page_size,
    )

    try:
        smoke.vertex_search_smoke(search_args)
    except SystemExit as exc:  # pragma: no cover - subprocess failure path
        return SearchSmokeResult(status="failed", message=str(exc))
    except Exception as exc:  # pragma: no cover - safety net
        return SearchSmokeResult(status="failed", message=str(exc))

    return SearchSmokeResult(status="success", message="Vertex search returned results.")


def write_reports(
    results: list[JobResult],
    smoke_result: SmokeResult | None,
    dossier_smoke: DossierSmokeResult | None,
    search_smoke: SearchSmokeResult | None,
    args: argparse.Namespace,
) -> None:
    args.report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    report = {
        "project": args.project,
        "region": args.region,
        "bundle_uri": args.bundle_uri,
        "dataset": args.dataset,
        "dry_run": args.dry_run,
        "verify_only": args.verify_only,
        "impersonated_service_account": args.wif_service_account,
        "timestamp": timestamp,
        "bundle_uri_provided": bool(args.bundle_uri),
        "dataset_provided": bool(args.dataset),
        "jobs": [
            {
                "label": r.label,
                "job_name": r.job_name,
                "status": r.status,
                "command": r.command,
                "stdout": r.stdout,
                "stderr": r.stderr,
                "error": r.error,
            }
            for r in results
        ],
        "smoke": None,
        "dossier_smoke": None,
        "search_smoke": None,
    }
    if smoke_result:
        report["smoke"] = {"status": smoke_result.status, "message": smoke_result.message}
    if dossier_smoke:
        report["dossier_smoke"] = {
            "status": dossier_smoke.status,
            "message": dossier_smoke.message,
            "plan_id": dossier_smoke.plan_id,
            "manifest_path": dossier_smoke.manifest_path,
            "signature_path": dossier_smoke.signature_path,
        }
    if search_smoke:
        report["search_smoke"] = {"status": search_smoke.status, "message": search_smoke.message}

    json_path = args.report_dir / "dev_bootstrap_report.json"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True))

    lines = [
        f"# Dev bootstrap report ({timestamp})",
        "",
        f"Project: {args.project}",
        f"Region: {args.region}",
        f"Bundle URI: {args.bundle_uri or '<none>'}",
        f"Dataset: {args.dataset or '<none>'}",
        f"Dry run: {args.dry_run}",
        f"Verify only: {args.verify_only}",
        f"Service account: {args.wif_service_account}",
        "",
        "## Jobs",
    ]
    for r in results:
        lines.append(f"- {r.label}: {r.status} ({r.job_name})")
    if smoke_result:
        lines.append("")
        lines.append("## Smoke")
        lines.append(f"- {smoke_result.status}: {smoke_result.message}")
    if dossier_smoke:
        lines.append("")
        lines.append("## Dossier smoke")
        lines.append(f"- {dossier_smoke.status}: {dossier_smoke.message}")
        if dossier_smoke.plan_id:
            lines.append(f"- plan_id: {dossier_smoke.plan_id}")
        if dossier_smoke.manifest_path:
            lines.append(f"- manifest: {dossier_smoke.manifest_path}")
        if dossier_smoke.signature_path:
            lines.append(f"- signature: {dossier_smoke.signature_path}")
    if search_smoke:
        lines.append("")
        lines.append("## Search smoke")
        lines.append(f"- {search_smoke.status}: {search_smoke.message}")

    (args.report_dir / "dev_bootstrap_report.md").write_text("\n".join(lines))


def bootstrap_dev(args: argparse.Namespace) -> int:
    configure_logging(args.log_level)
    guard_environment(args.project, args.force)

    if not args.search_project:
        args.search_project = args.project
    if not args.search_location:
        args.search_location = "global"

    bundle_uri_display, bundle_sha = summarize_bundle(args.bundle_uri)
    if bundle_uri_display:
        logging.info("Bundle URI: %s", bundle_uri_display)
    if bundle_sha:
        logging.info("Bundle sha256: %s", bundle_sha)

    logging.info(
        "Bootstrap dev: project=%s region=%s bundle=%s " "dataset=%s dry_run=%s verify_only=%s run_smoke=%s",
        args.project,
        args.region,
        args.bundle_uri or "<none>",
        args.dataset or "<none>",
        args.dry_run,
        args.verify_only,
        args.run_smoke,
    )

    specs = build_job_specs(args)
    if not specs and not args.verify_only:
        logging.warning("No jobs selected; nothing to do.")
        return 0

    results: list[JobResult] = []
    if not args.verify_only:
        for spec in specs:
            try:
                results.append(execute_job(spec, args))
            except subprocess.CalledProcessError as exc:
                results.append(
                    JobResult(
                        label=spec.label,
                        job_name=spec.job_name,
                        command=format_command(
                            ["gcloud", "run", "jobs", "execute", spec.job_name],
                            redacted_flags={"--impersonate-service-account"},
                        ),
                        status="failed",
                        stdout=exc.stdout or "",
                        stderr=exc.stderr or "",
                        error=str(exc),
                    )
                )
                write_reports(results, None, None, None, args)
                return 1
    else:
        logging.info("verify-only set; skipping job execution.")

    smoke_result: SmokeResult | None = None
    if args.run_smoke or args.verify_only:
        logging.info("Running Cloud Run smoke...")
        smoke_result = run_smoke(args)
        if smoke_result.status != "success":
            write_reports(results, smoke_result, None, None, args)
            logging.error("Smoke failed: %s", smoke_result.message)
            return 1

    dossier_smoke: DossierSmokeResult | None = None
    if args.run_dossier_smoke:
        logging.info("Running dossier smoke...")
        dossier_smoke = run_dossier_smoke(args)
        if dossier_smoke.status == "failed":
            write_reports(results, smoke_result, dossier_smoke, None, args)
            logging.error("Dossier smoke failed: %s", dossier_smoke.message)
            return 1

    search_smoke: SearchSmokeResult | None = None
    if args.run_search_smoke:
        logging.info("Running search smoke...")
        search_smoke = run_search_smoke(args)
        if search_smoke.status == "failed":
            write_reports(results, smoke_result, dossier_smoke, search_smoke, args)
            logging.error("Search smoke failed: %s", search_smoke.message)
            return 1

    write_reports(results, smoke_result, dossier_smoke, search_smoke, args)
    logging.info("Dev bootstrap completed.")
    return 0


def run_dev(
    *,
    project: str,
    region: str,
    bundle_uri: Optional[str],
    dataset: Optional[str],
    wif_service_account: str,
    firestore_job: str,
    vertex_job: str,
    sql_job: str,
    bigquery_job: str,
    gcs_assets_job: str,
    reports_job: str,
    saved_searches_job: str,
    skip_firestore: bool,
    skip_vertex: bool,
    skip_sql: bool,
    skip_bigquery: bool,
    skip_gcs_assets: bool,
    skip_reports: bool,
    skip_saved_searches: bool,
    dry_run: bool,
    verify_only: bool,
    run_smoke: bool,
    run_dossier_smoke: bool,
    run_search_smoke: bool,
    search_project: Optional[str],
    search_location: Optional[str],
    search_data_store_id: Optional[str],
    search_serving_config_id: Optional[str],
    search_query: str,
    search_page_size: int,
    report_dir: Path,
    force: bool,
    log_level: str,
    smoke_api_url: str,
    smoke_token: str,
    smoke_job: str,
    smoke_container: str,
) -> int:
    args = argparse.Namespace(
        project=project,
        region=region,
        bundle_uri=bundle_uri,
        dataset=dataset,
        wif_service_account=wif_service_account,
        firestore_job=firestore_job,
        vertex_job=vertex_job,
        sql_job=sql_job,
        bigquery_job=bigquery_job,
        gcs_assets_job=gcs_assets_job,
        reports_job=reports_job,
        saved_searches_job=saved_searches_job,
        skip_firestore=skip_firestore,
        skip_vertex=skip_vertex,
        skip_sql=skip_sql,
        skip_bigquery=skip_bigquery,
        skip_gcs_assets=skip_gcs_assets,
        skip_reports=skip_reports,
        skip_saved_searches=skip_saved_searches,
        dry_run=dry_run,
        verify_only=verify_only,
        run_smoke=run_smoke,
        run_dossier_smoke=run_dossier_smoke,
        run_search_smoke=run_search_smoke,
        search_project=search_project,
        search_location=search_location,
        search_data_store_id=search_data_store_id,
        search_serving_config_id=search_serving_config_id,
        search_query=search_query,
        search_page_size=search_page_size,
        report_dir=report_dir,
        force=force,
        log_level=log_level,
        smoke_api_url=smoke_api_url,
        smoke_token=smoke_token,
        smoke_job=smoke_job,
        smoke_container=smoke_container,
    )
    return bootstrap_dev(args)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    return run_dev(
        project=args.project,
        region=args.region,
        bundle_uri=args.bundle_uri,
        dataset=args.dataset,
        wif_service_account=args.wif_service_account,
        firestore_job=args.firestore_job,
        vertex_job=args.vertex_job,
        sql_job=args.sql_job,
        bigquery_job=args.bigquery_job,
        gcs_assets_job=args.gcs_assets_job,
        reports_job=args.reports_job,
        saved_searches_job=args.saved_searches_job,
        skip_firestore=args.skip_firestore,
        skip_vertex=args.skip_vertex,
        skip_sql=args.skip_sql,
        skip_bigquery=args.skip_bigquery,
        skip_gcs_assets=args.skip_gcs_assets,
        skip_reports=args.skip_reports,
        skip_saved_searches=args.skip_saved_searches,
        dry_run=args.dry_run,
        verify_only=args.verify_only,
        run_smoke=args.run_smoke,
        run_dossier_smoke=args.run_dossier_smoke,
        run_search_smoke=args.run_search_smoke,
        search_project=args.search_project,
        search_location=args.search_location,
        search_data_store_id=args.search_data_store_id,
        search_serving_config_id=args.search_serving_config_id,
        search_query=args.search_query,
        search_page_size=args.search_page_size,
        report_dir=args.report_dir,
        force=args.force,
        log_level=args.log_level,
        smoke_api_url=args.smoke_api_url,
        smoke_token=args.smoke_token,
        smoke_job=args.smoke_job,
        smoke_container=args.smoke_container,
    )


dev_app = typer.Typer(help="Bootstrap dev via Cloud Run jobs and optional smokes.")


def _exit_from_return(code: int | None) -> None:
    """Honor integer return codes from invoked helpers."""

    if isinstance(code, int) and code != 0:
        raise typer.Exit(code)


@dev_app.command("reset", help="Run dev bootstrap jobs (Cloud Run) with optional smoke.")
def bootstrap_dev_reset(
    project: str = typer.Option(DEFAULT_PROJECT, "--project", help="Target GCP project (default: i4g-dev)."),
    region: str = typer.Option(DEFAULT_REGION, "--region", help="Cloud Run region (default: us-central1)."),
    bundle_uri: Optional[str] = typer.Option(None, "--bundle-uri", help="Bundle URI passed to jobs, if supported."),
    dataset: Optional[str] = typer.Option(None, "--dataset", help="Dataset identifier injected into job args."),
    wif_service_account: str = typer.Option(
        DEFAULT_WIF_SA,
        "--wif-service-account",
        help="Service account to impersonate via WIF.",
    ),
    firestore_job: str = typer.Option(DEFAULT_JOBS["firestore"], "--firestore-job", help="Firestore refresh job."),
    vertex_job: str = typer.Option(DEFAULT_JOBS["vertex"], "--vertex-job", help="Vertex import job."),
    sql_job: str = typer.Option(DEFAULT_JOBS["sql"], "--sql-job", help="SQL/Firestore sync job."),
    bigquery_job: str = typer.Option(DEFAULT_JOBS["bigquery"], "--bigquery-job", help="BigQuery refresh job."),
    gcs_assets_job: str = typer.Option(DEFAULT_JOBS["gcs_assets"], "--gcs-assets-job", help="GCS asset sync job."),
    reports_job: str = typer.Option(DEFAULT_JOBS["reports"], "--reports-job", help="Reports/dossiers job."),
    saved_searches_job: str = typer.Option(
        DEFAULT_JOBS["saved_searches"], "--saved-searches-job", help="Saved searches/tag presets job."
    ),
    skip_firestore: bool = typer.Option(False, "--skip-firestore", help="Skip Firestore refresh job."),
    skip_vertex: bool = typer.Option(False, "--skip-vertex", help="Skip Vertex import job."),
    skip_sql: bool = typer.Option(False, "--skip-sql", help="Skip SQL/Firestore sync job."),
    skip_bigquery: bool = typer.Option(False, "--skip-bigquery", help="Skip BigQuery refresh job."),
    skip_gcs_assets: bool = typer.Option(False, "--skip-gcs-assets", help="Skip GCS asset sync job."),
    skip_reports: bool = typer.Option(False, "--skip-reports", help="Skip reports/dossiers job."),
    skip_saved_searches: bool = typer.Option(False, "--skip-saved-searches", help="Skip saved searches job."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print planned commands without executing."),
    run_smoke: bool = typer.Option(False, "--run-smoke/--no-run-smoke", help="Run Cloud Run intake smoke."),
    run_dossier_smoke: bool = typer.Option(
        False, "--run-dossier-smoke/--no-run-dossier-smoke", help="Run dossier verification smoke."
    ),
    run_search_smoke: bool = typer.Option(
        False, "--run-search-smoke/--no-run-search-smoke", help="Run Vertex search smoke."
    ),
    search_project: Optional[str] = typer.Option(
        None, "--search-project", help="Vertex project for search smoke (defaults to --project)."
    ),
    search_location: Optional[str] = typer.Option(
        None, "--search-location", help="Vertex location for search smoke (default from orchestrator)."
    ),
    search_data_store_id: Optional[str] = typer.Option(
        None, "--search-data-store-id", help="Vertex data store id for search smoke."
    ),
    search_serving_config_id: str = typer.Option(
        "default_search", "--search-serving-config-id", help="Vertex serving config id for search smoke."
    ),
    search_query: str = typer.Option("wallet address verification", "--search-query", help="Search smoke query."),
    search_page_size: int = typer.Option(5, "--search-page-size", help="Result page size for search smoke."),
    report_dir: Path = typer.Option(
        DEFAULT_REPORT_DIR, "--report-dir", help="Directory to write JSON/Markdown reports."
    ),
    force: bool = typer.Option(False, "--force", help="Allow targeting non-dev projects (never prod)."),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging verbosity (DEBUG/INFO/WARNING/ERROR)."),
    smoke_api_url: str = typer.Option(
        os.getenv("I4G_SMOKE_API_URL", "https://api.intelligenceforgood.org"),
        "--smoke-api-url",
        help="API base URL for smoke.",
    ),
    smoke_token: str = typer.Option(
        os.getenv("I4G_SMOKE_TOKEN", "dev-analyst-token"), "--smoke-token", help="API token for smoke."
    ),
    smoke_job: str = typer.Option(
        os.getenv("I4G_SMOKE_JOB", "process-intakes"), "--smoke-job", help="Cloud Run job to execute for smoke."
    ),
    smoke_container: str = typer.Option(
        os.getenv("I4G_SMOKE_CONTAINER", "container-0"), "--smoke-container", help="Container for smoke job."
    ),
) -> None:
    """Execute dev Cloud Run bootstrap jobs; optional smoke after run."""

    _exit_from_return(
        run_dev(
            project=project,
            region=region,
            bundle_uri=bundle_uri,
            dataset=dataset,
            wif_service_account=wif_service_account,
            firestore_job=firestore_job,
            vertex_job=vertex_job,
            sql_job=sql_job,
            bigquery_job=bigquery_job,
            gcs_assets_job=gcs_assets_job,
            reports_job=reports_job,
            saved_searches_job=saved_searches_job,
            skip_firestore=skip_firestore,
            skip_vertex=skip_vertex,
            skip_sql=skip_sql,
            skip_bigquery=skip_bigquery,
            skip_gcs_assets=skip_gcs_assets,
            skip_reports=skip_reports,
            skip_saved_searches=skip_saved_searches,
            dry_run=dry_run,
            verify_only=False,
            run_smoke=run_smoke,
            run_dossier_smoke=run_dossier_smoke,
            run_search_smoke=run_search_smoke,
            search_project=search_project,
            search_location=search_location,
            search_data_store_id=search_data_store_id,
            search_serving_config_id=search_serving_config_id,
            search_query=search_query,
            search_page_size=search_page_size,
            report_dir=report_dir,
            force=force,
            log_level=log_level,
            smoke_api_url=smoke_api_url,
            smoke_token=smoke_token,
            smoke_job=smoke_job,
            smoke_container=smoke_container,
        )
    )


@dev_app.command("load", help="Alias of reset for dev bootstrap jobs.")
def bootstrap_dev_load(
    project: str = typer.Option(DEFAULT_PROJECT, "--project", help="Target GCP project (default: i4g-dev)."),
    region: str = typer.Option(DEFAULT_REGION, "--region", help="Cloud Run region (default: us-central1)."),
    bundle_uri: Optional[str] = typer.Option(None, "--bundle-uri", help="Bundle URI passed to jobs, if supported."),
    dataset: Optional[str] = typer.Option(None, "--dataset", help="Dataset identifier injected into job args."),
    wif_service_account: str = typer.Option(
        DEFAULT_WIF_SA,
        "--wif-service-account",
        help="Service account to impersonate via WIF.",
    ),
    firestore_job: str = typer.Option(DEFAULT_JOBS["firestore"], "--firestore-job", help="Firestore refresh job."),
    vertex_job: str = typer.Option(DEFAULT_JOBS["vertex"], "--vertex-job", help="Vertex import job."),
    sql_job: str = typer.Option(DEFAULT_JOBS["sql"], "--sql-job", help="SQL/Firestore sync job."),
    bigquery_job: str = typer.Option(DEFAULT_JOBS["bigquery"], "--bigquery-job", help="BigQuery refresh job."),
    gcs_assets_job: str = typer.Option(DEFAULT_JOBS["gcs_assets"], "--gcs-assets-job", help="GCS asset sync job."),
    reports_job: str = typer.Option(DEFAULT_JOBS["reports"], "--reports-job", help="Reports/dossiers job."),
    saved_searches_job: str = typer.Option(
        DEFAULT_JOBS["saved_searches"], "--saved-searches-job", help="Saved searches/tag presets job."
    ),
    skip_firestore: bool = typer.Option(False, "--skip-firestore", help="Skip Firestore refresh job."),
    skip_vertex: bool = typer.Option(False, "--skip-vertex", help="Skip Vertex import job."),
    skip_sql: bool = typer.Option(False, "--skip-sql", help="Skip SQL/Firestore sync job."),
    skip_bigquery: bool = typer.Option(False, "--skip-bigquery", help="Skip BigQuery refresh job."),
    skip_gcs_assets: bool = typer.Option(False, "--skip-gcs-assets", help="Skip GCS asset sync job."),
    skip_reports: bool = typer.Option(False, "--skip-reports", help="Skip reports/dossiers job."),
    skip_saved_searches: bool = typer.Option(False, "--skip-saved-searches", help="Skip saved searches job."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print planned commands without executing."),
    run_smoke: bool = typer.Option(False, "--run-smoke/--no-run-smoke", help="Run Cloud Run intake smoke."),
    run_dossier_smoke: bool = typer.Option(
        False, "--run-dossier-smoke/--no-run-dossier-smoke", help="Run dossier verification smoke."
    ),
    run_search_smoke: bool = typer.Option(
        False, "--run-search-smoke/--no-run-search-smoke", help="Run Vertex search smoke."
    ),
    search_project: Optional[str] = typer.Option(
        None, "--search-project", help="Vertex project for search smoke (defaults to --project)."
    ),
    search_location: Optional[str] = typer.Option(
        None, "--search-location", help="Vertex location for search smoke (default from orchestrator)."
    ),
    search_data_store_id: Optional[str] = typer.Option(
        None, "--search-data-store-id", help="Vertex data store id for search smoke."
    ),
    search_serving_config_id: str = typer.Option(
        "default_search", "--search-serving-config-id", help="Vertex serving config id for search smoke."
    ),
    search_query: str = typer.Option("wallet address verification", "--search-query", help="Search smoke query."),
    search_page_size: int = typer.Option(5, "--search-page-size", help="Result page size for search smoke."),
    report_dir: Path = typer.Option(
        DEFAULT_REPORT_DIR, "--report-dir", help="Directory to write JSON/Markdown reports."
    ),
    force: bool = typer.Option(False, "--force", help="Allow targeting non-dev projects (never prod)."),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging verbosity (DEBUG/INFO/WARNING/ERROR)."),
    smoke_api_url: str = typer.Option(
        os.getenv("I4G_SMOKE_API_URL", "https://api.intelligenceforgood.org"),
        "--smoke-api-url",
        help="API base URL for smoke.",
    ),
    smoke_token: str = typer.Option(
        os.getenv("I4G_SMOKE_TOKEN", "dev-analyst-token"), "--smoke-token", help="API token for smoke."
    ),
    smoke_job: str = typer.Option(
        os.getenv("I4G_SMOKE_JOB", "process-intakes"), "--smoke-job", help="Cloud Run job to execute for smoke."
    ),
    smoke_container: str = typer.Option(
        os.getenv("I4G_SMOKE_CONTAINER", "container-0"), "--smoke-container", help="Container for smoke job."
    ),
) -> None:
    """Alias of reset for dev bootstrap jobs (kept for symmetry)."""

    _exit_from_return(
        run_dev(
            project=project,
            region=region,
            bundle_uri=bundle_uri,
            dataset=dataset,
            wif_service_account=wif_service_account,
            firestore_job=firestore_job,
            vertex_job=vertex_job,
            sql_job=sql_job,
            bigquery_job=bigquery_job,
            gcs_assets_job=gcs_assets_job,
            reports_job=reports_job,
            saved_searches_job=saved_searches_job,
            skip_firestore=skip_firestore,
            skip_vertex=skip_vertex,
            skip_sql=skip_sql,
            skip_bigquery=skip_bigquery,
            skip_gcs_assets=skip_gcs_assets,
            skip_reports=skip_reports,
            skip_saved_searches=skip_saved_searches,
            dry_run=dry_run,
            verify_only=False,
            run_smoke=run_smoke,
            run_dossier_smoke=run_dossier_smoke,
            run_search_smoke=run_search_smoke,
            search_project=search_project,
            search_location=search_location,
            search_data_store_id=search_data_store_id,
            search_serving_config_id=search_serving_config_id,
            search_query=search_query,
            search_page_size=search_page_size,
            report_dir=report_dir,
            force=force,
            log_level=log_level,
            smoke_api_url=smoke_api_url,
            smoke_token=smoke_token,
            smoke_job=smoke_job,
            smoke_container=smoke_container,
        )
    )


@dev_app.command("verify", help="Run verification-only flow for dev (smoke optional).")
def bootstrap_dev_verify(
    project: str = typer.Option(DEFAULT_PROJECT, "--project", help="Target GCP project (default: i4g-dev)."),
    region: str = typer.Option(DEFAULT_REGION, "--region", help="Cloud Run region (default: us-central1)."),
    bundle_uri: Optional[str] = typer.Option(None, "--bundle-uri", help="Bundle URI passed to jobs, if supported."),
    dataset: Optional[str] = typer.Option(None, "--dataset", help="Dataset identifier injected into job args."),
    wif_service_account: str = typer.Option(
        DEFAULT_WIF_SA,
        "--wif-service-account",
        help="Service account to impersonate via WIF.",
    ),
    firestore_job: str = typer.Option(DEFAULT_JOBS["firestore"], "--firestore-job", help="Firestore refresh job."),
    vertex_job: str = typer.Option(DEFAULT_JOBS["vertex"], "--vertex-job", help="Vertex import job."),
    sql_job: str = typer.Option(DEFAULT_JOBS["sql"], "--sql-job", help="SQL/Firestore sync job."),
    bigquery_job: str = typer.Option(DEFAULT_JOBS["bigquery"], "--bigquery-job", help="BigQuery refresh job."),
    gcs_assets_job: str = typer.Option(DEFAULT_JOBS["gcs_assets"], "--gcs-assets-job", help="GCS asset sync job."),
    reports_job: str = typer.Option(DEFAULT_JOBS["reports"], "--reports-job", help="Reports/dossiers job."),
    saved_searches_job: str = typer.Option(
        DEFAULT_JOBS["saved_searches"], "--saved-searches-job", help="Saved searches/tag presets job."
    ),
    run_smoke: bool = typer.Option(True, "--run-smoke/--no-run-smoke", help="Run Cloud Run intake smoke."),
    run_dossier_smoke: bool = typer.Option(
        True, "--run-dossier-smoke/--no-run-dossier-smoke", help="Run dossier verification smoke."
    ),
    run_search_smoke: bool = typer.Option(
        True, "--run-search-smoke/--no-run-search-smoke", help="Run Vertex search smoke."
    ),
    search_project: Optional[str] = typer.Option(
        None, "--search-project", help="Vertex project for search smoke (defaults to --project)."
    ),
    search_location: Optional[str] = typer.Option(
        None, "--search-location", help="Vertex location for search smoke (default from orchestrator)."
    ),
    search_data_store_id: Optional[str] = typer.Option(
        None, "--search-data-store-id", help="Vertex data store id for search smoke."
    ),
    search_serving_config_id: str = typer.Option(
        "default_search", "--search-serving-config-id", help="Vertex serving config id for search smoke."
    ),
    search_query: str = typer.Option("wallet address verification", "--search-query", help="Search smoke query."),
    search_page_size: int = typer.Option(5, "--search-page-size", help="Result page size for search smoke."),
    report_dir: Path = typer.Option(
        DEFAULT_REPORT_DIR, "--report-dir", help="Directory to write JSON/Markdown reports."
    ),
    force: bool = typer.Option(False, "--force", help="Allow targeting non-dev projects (never prod)."),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging verbosity (DEBUG/INFO/WARNING/ERROR)."),
    smoke_api_url: str = typer.Option(
        os.getenv("I4G_SMOKE_API_URL", "https://api.intelligenceforgood.org"),
        "--smoke-api-url",
        help="API base URL for smoke.",
    ),
    smoke_token: str = typer.Option(
        os.getenv("I4G_SMOKE_TOKEN", "dev-analyst-token"), "--smoke-token", help="API token for smoke."
    ),
    smoke_job: str = typer.Option(
        os.getenv("I4G_SMOKE_JOB", "process-intakes"), "--smoke-job", help="Cloud Run job to execute for smoke."
    ),
    smoke_container: str = typer.Option(
        os.getenv("I4G_SMOKE_CONTAINER", "container-0"), "--smoke-container", help="Container for smoke job."
    ),
) -> None:
    """Skip job execution and only run verification/smoke for dev."""

    _exit_from_return(
        run_dev(
            project=project,
            region=region,
            bundle_uri=bundle_uri,
            dataset=dataset,
            wif_service_account=wif_service_account,
            firestore_job=firestore_job,
            vertex_job=vertex_job,
            sql_job=sql_job,
            bigquery_job=bigquery_job,
            gcs_assets_job=gcs_assets_job,
            reports_job=reports_job,
            saved_searches_job=saved_searches_job,
            skip_firestore=False,
            skip_vertex=False,
            skip_sql=False,
            skip_bigquery=False,
            skip_gcs_assets=False,
            skip_reports=False,
            skip_saved_searches=False,
            dry_run=False,
            verify_only=True,
            run_smoke=run_smoke,
            run_dossier_smoke=run_dossier_smoke,
            run_search_smoke=run_search_smoke,
            search_project=search_project,
            search_location=search_location,
            search_data_store_id=search_data_store_id,
            search_serving_config_id=search_serving_config_id,
            search_query=search_query,
            search_page_size=search_page_size,
            report_dir=report_dir,
            force=force,
            log_level=log_level,
            smoke_api_url=smoke_api_url,
            smoke_token=smoke_token,
            smoke_job=smoke_job,
            smoke_container=smoke_container,
        )
    )


@dev_app.command("smoke", help="Run dev smoke only (no bootstrap jobs).")
def bootstrap_dev_smoke(
    project: str = typer.Option(DEFAULT_PROJECT, "--project", help="Target GCP project (default: i4g-dev)."),
    region: str = typer.Option(DEFAULT_REGION, "--region", help="Cloud Run region (default: us-central1)."),
    smoke_api_url: str = typer.Option(
        os.getenv("I4G_SMOKE_API_URL", "https://fastapi-gateway-y5jge5w2cq-uc.a.run.app"),
        "--smoke-api-url",
        help="API base URL for smoke.",
    ),
    smoke_token: str = typer.Option(
        os.getenv("I4G_SMOKE_TOKEN", "dev-analyst-token"), "--smoke-token", help="API token for smoke."
    ),
    smoke_job: str = typer.Option(
        os.getenv("I4G_SMOKE_JOB", "process-intakes"), "--smoke-job", help="Cloud Run job to execute for smoke."
    ),
    smoke_container: str = typer.Option(
        os.getenv("I4G_SMOKE_CONTAINER", "container-0"), "--smoke-container", help="Container for smoke job."
    ),
    report_dir: Path = typer.Option(
        DEFAULT_REPORT_DIR, "--report-dir", help="Directory to write JSON/Markdown reports."
    ),
    force: bool = typer.Option(False, "--force", help="Allow targeting non-dev projects (never prod)."),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging verbosity (DEBUG/INFO/WARNING/ERROR)."),
) -> None:
    """Run only Cloud Run smoke checks without bootstrapping jobs."""

    _exit_from_return(
        run_dev(
            project=project,
            region=region,
            bundle_uri=None,
            dataset=None,
            wif_service_account=DEFAULT_WIF_SA,
            firestore_job="",
            vertex_job="",
            sql_job="",
            bigquery_job="",
            gcs_assets_job="",
            reports_job="",
            saved_searches_job="",
            skip_firestore=True,
            skip_vertex=True,
            skip_sql=True,
            skip_bigquery=True,
            skip_gcs_assets=True,
            skip_reports=True,
            skip_saved_searches=True,
            dry_run=False,
            verify_only=True,
            run_smoke=True,
            run_dossier_smoke=False,
            run_search_smoke=False,
            search_project=None,
            search_location=None,
            search_data_store_id=None,
            search_serving_config_id=None,
            search_query="wallet address verification",
            search_page_size=5,
            report_dir=report_dir,
            force=force,
            log_level=log_level,
            smoke_api_url=smoke_api_url,
            smoke_token=smoke_token,
            smoke_job=smoke_job,
            smoke_container=smoke_container,
        )
    )


__all__ = ["run_dev", "main", "parse_args", "dev_app"]
