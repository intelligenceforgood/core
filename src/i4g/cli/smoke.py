"""Smoke helpers for the Typer CLI."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any, Dict, Tuple

from google.cloud import discoveryengine_v1beta as discoveryengine

from i4g.cli.ingest import ingest_vertex_search
from i4g.cli.utils import console


def vertex_search_smoke(args: Any) -> None:
    """Run a dry-run ingest then execute a Vertex search to verify connectivity."""

    dry_run_exit = ingest_vertex_search(
        type(
            "VertexArgs",
            (),
            {
                "project": args.project,
                "location": args.location,
                "branch_id": "default_branch",
                "data_store_id": args.data_store_id,
                "jsonl": args.jsonl,
                "dataset": None,
                "batch_size": 50,
                "reconcile_mode": "INCREMENTAL",
                "dry_run": True,
                "verbose": False,
            },
        )()
    )
    if dry_run_exit != 0:
        raise SystemExit("Dry-run ingestion failed; see logs above.")

    client = discoveryengine.SearchServiceClient()
    serving_config = client.serving_config_path(
        project=args.project,
        location=args.location,
        data_store=args.data_store_id,
        serving_config=args.serving_config_id,
    )
    request = discoveryengine.SearchRequest(
        serving_config=serving_config,
        query=args.query,
        page_size=args.page_size,
    )
    results = list(client.search(request=request))
    if not results:
        raise SystemExit("Search returned no results; ingestion may be empty.")
    top = results[0].document
    summary = top.struct_data.get("summary") if top.struct_data else None
    console.print(
        "[green]✅ Vertex search smoke:[/green] %d result(s) (top id=%s, summary=%s)"
        % (len(results), top.id, summary or top.title or "<unknown>")
    )


class SmokeError(RuntimeError):
    """Raised when any Cloud Run smoke step fails."""


@dataclass
class SmokeResult:
    intake_id: str
    job_id: str
    execution_name: str
    intake_status: str
    job_status: str


def _run_command(cmd: list[str], *, capture_output: bool = True, check: bool = True) -> subprocess.CompletedProcess:
    """Run a shell command and return the completed process."""

    try:
        return subprocess.run(
            cmd,
            check=check,
            capture_output=capture_output,
            text=True,
        )
    except subprocess.CalledProcessError as exc:  # pragma: no cover - subprocess failure path
        message = f"Command failed ({' '.join(cmd)}): {exc.stderr or exc.stdout}"
        raise SmokeError(message) from exc


def _submit_intake(api_url: str, token: str) -> Tuple[str, str]:
    payload = {
        "reporter_name": "Dev Smoke",
        "summary": "Automated dev smoke submission",
        "details": "Submitted by i4g smoke cloud-run",
        "source": "smoke-test",
    }
    curl_cmd = [
        "curl",
        "-sS",
        "-L",
        "-o",
        "-",
        "-w",
        "%{http_code}",
        "-X",
        "POST",
        f"{api_url}/intakes/",
        "-H",
        f"X-API-KEY: {token}",
        "-F",
        f"payload={json.dumps(payload)}",
    ]

    proc = _run_command(curl_cmd)
    raw_output = proc.stdout
    body, status_code = raw_output[:-3], raw_output[-3:]
    if status_code != "201":
        raise SmokeError(f"Intake submission failed (status {status_code}): {body}")

    try:
        response = json.loads(body)
    except json.JSONDecodeError as exc:
        raise SmokeError(f"Invalid JSON from intake submission: {body}") from exc

    intake_id = response.get("intake_id")
    job_id = response.get("job_id")
    if not intake_id or not job_id:
        raise SmokeError(f"Missing intake or job id in response: {response}")

    return intake_id, job_id


def _execute_job(project: str, region: str, job: str, container: str, intake_id: str, job_id: str) -> str:
    env_overrides = f"I4G_INTAKE__ID={intake_id},I4G_INTAKE__JOB_ID={job_id}"
    cmd = [
        "gcloud",
        "run",
        "jobs",
        "execute",
        job,
        "--project",
        project,
        "--region",
        region,
        "--wait",
        "--container",
        container,
        f"--update-env-vars={env_overrides}",
    ]

    proc = _run_command(cmd)
    stdout = proc.stdout
    marker = "Execution ["
    start = stdout.find(marker)
    if start != -1:
        start += len(marker)
        end = stdout.find("]", start)
        if end != -1:
            return stdout[start:end]

    describe_cmd = [
        "gcloud",
        "run",
        "jobs",
        "describe",
        job,
        "--project",
        project,
        "--region",
        region,
        "--format",
        "value(status.latestCreatedExecution.name)",
    ]
    describe_proc = _run_command(describe_cmd)
    execution_name = describe_proc.stdout.strip()
    if not execution_name:
        raise SmokeError(f"Could not determine execution name. gcloud output: {stdout}")
    return execution_name


def _fetch_intake(api_url: str, intake_id: str, token: str) -> Dict[str, Any]:
    cmd = [
        "curl",
        "-sS",
        "-H",
        f"X-API-KEY: {token}",
        f"{api_url}/intakes/{intake_id}",
    ]
    proc = _run_command(cmd)
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise SmokeError(f"Invalid JSON when fetching intake: {proc.stdout}") from exc


def cloud_run_smoke(args: Any) -> None:
    """Run the dev Cloud Run intake smoke end-to-end."""

    try:
        intake_id, job_id = _submit_intake(args.api_url.rstrip("/"), args.token)
        execution_name = _execute_job(args.project, args.region, args.job, args.container, intake_id, job_id)
        intake = _fetch_intake(args.api_url.rstrip("/"), intake_id, args.token)
    except SmokeError as exc:
        raise SystemExit(f"Smoke test failed: {exc}") from exc

    status = intake.get("status")
    job_status = intake.get("job", {}).get("status")
    if status != "processed" or job_status != "completed":
        raise SystemExit(
            "Unexpected intake status after job execution: " f"status={status!r}, job_status={job_status!r}"
        )

    result = SmokeResult(
        intake_id=intake_id,
        job_id=job_id,
        execution_name=execution_name,
        intake_status=status,
        job_status=job_status,
    )

    console.print(
        json.dumps(
            {
                "intake_id": result.intake_id,
                "job_id": result.job_id,
                "execution": result.execution_name,
                "intake_status": result.intake_status,
                "job_status": result.job_status,
            },
            indent=2,
        )
    )


__all__ = ["vertex_search_smoke", "cloud_run_smoke"]
