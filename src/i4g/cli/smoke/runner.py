"""Smoke helpers for the Typer CLI."""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Dict, Tuple

from google.cloud import discoveryengine_v1beta as discoveryengine

from i4g.cli.ingest.logic import ingest_vertex_search
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


def _submit_intake(api_url: str, token: str, iap_token: str | None = None) -> Tuple[str, str]:
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
    ]
    if iap_token:
        curl_cmd.extend(["-H", f"Authorization: Bearer {iap_token}"])

    curl_cmd.extend(
        [
            "-F",
            f"payload={json.dumps(payload)}",
        ]
    )

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


def _print_logs(execution_name: str, project: str, region: str) -> None:
    cmd = [
        "gcloud",
        "beta",
        "run",
        "jobs",
        "executions",
        "logs",
        "read",
        execution_name,
        "--project",
        project,
        "--region",
        region,
        "--limit",
        "50",
    ]
    proc = _run_command(cmd, check=False)
    if proc.returncode == 0:
        console.print(proc.stdout)
    else:
        console.print(f"Failed to fetch logs: {proc.stderr}")


def _execute_job(
    project: str,
    region: str,
    job: str,
    container: str,
    intake_id: str,
    job_id: str,
    api_url: str | None = None,
    api_key: str | None = None,
    impersonate_service_account: str | None = None,
) -> str:
    # Workaround for gcloud 550.0.0 bug (delayExecution): use curl to trigger job
    cmd = ["gcloud", "auth", "print-access-token"]
    if impersonate_service_account:
        cmd.extend(["--impersonate-service-account", impersonate_service_account])

    token_proc = _run_command(cmd)
    access_token = token_proc.stdout.strip()

    url = f"https://run.googleapis.com/v2/projects/{project}/locations/{region}/jobs/{job}:run"

    env_vars = [
        {"name": "I4G_INTAKE__ID", "value": intake_id},
        {"name": "I4G_INTAKE__JOB_ID", "value": job_id},
    ]
    if api_url:
        env_vars.append({"name": "I4G_API__URL", "value": api_url})
    if api_key:
        env_vars.append({"name": "I4G_API__KEY", "value": api_key})

    payload = {
        "overrides": {
            "containerOverrides": [
                {
                    "name": container,
                    "env": env_vars,
                }
            ]
        }
    }

    curl_cmd = [
        "curl",
        "-sS",
        "-X",
        "POST",
        url,
        "-H",
        f"Authorization: Bearer {access_token}",
        "-H",
        "Content-Type: application/json",
        "-d",
        json.dumps(payload),
    ]

    proc = _run_command(curl_cmd)
    if proc.returncode != 0:
        raise SmokeError(f"Failed to trigger job: {proc.stderr}")

    # Check for HTTP errors in stdout (since curl -sS writes response body to stdout)
    # If the response is not JSON or contains an error field, it might be a 403/404/500
    try:
        resp = json.loads(proc.stdout)
        if "error" in resp:
            error_msg = json.dumps(resp["error"])
            raise SmokeError(f"Job trigger failed (API error): {error_msg}")

        full_name = resp["metadata"]["name"]
        execution_name = full_name.split("/")[-1]
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        # If we can't parse JSON, it might be a raw error message or HTML
        raise SmokeError(f"Failed to parse job execution response: {proc.stdout}") from exc

    console.print(f"Job triggered: {execution_name}. Waiting for completion...")

    start_time = time.time()
    while time.time() - start_time < 600:  # 10 min timeout
        cmd = [
            "gcloud",
            "run",
            "jobs",
            "executions",
            "describe",
            execution_name,
            "--project",
            project,
            "--region",
            region,
            "--format=json",
        ]
        proc = _run_command(cmd, check=False)
        if proc.returncode != 0:
            console.print(f"Polling failed (code {proc.returncode}). Retrying...")
            time.sleep(5)
            continue

        status = json.loads(proc.stdout)
        conditions = status.get("status", {}).get("conditions", [])
        completed = next((c for c in conditions if c["type"] == "Completed"), None)

        if completed:
            status_str = completed.get("status")
            message = completed.get("message")
            if status_str == "True":
                console.print(f"Job completed successfully: {message}")
                return execution_name
            elif status_str == "False":
                console.print(f"Job execution failed: {message}")
                console.print("Fetching logs...")
                _print_logs(execution_name, project, region)
                raise SmokeError(f"Job execution failed: {message}")
            else:
                # Unknown/Running
                console.print(f"Job running... ({message})")
        else:
            console.print("Job status unknown...")

        time.sleep(10)

    raise SmokeError(f"Job execution timed out: {execution_name}")


def _fetch_intake(api_url: str, intake_id: str, token: str, iap_token: str | None = None) -> Dict[str, Any]:
    cmd = [
        "curl",
        "-sS",
        "-H",
        f"X-API-KEY: {token}",
    ]
    if iap_token:
        cmd.extend(["-H", f"Authorization: Bearer {iap_token}"])

    cmd.append(f"{api_url}/intakes/{intake_id}")

    proc = _run_command(cmd)
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise SmokeError(f"Invalid JSON when fetching intake: {proc.stdout}") from exc


def cloud_run_smoke(args: Any) -> None:
    """Run the dev Cloud Run intake smoke end-to-end."""
    iap_token = getattr(args, "iap_token", None)
    impersonate_sa = getattr(args, "impersonate_service_account", None)

    try:
        intake_id, job_id = _submit_intake(args.api_url.rstrip("/"), args.token, iap_token)
        execution_name = _execute_job(
            args.project,
            args.region,
            args.job,
            args.container,
            intake_id,
            job_id,
            api_url=args.api_url,
            api_key=args.token,
            impersonate_service_account=impersonate_sa,
        )
        intake = _fetch_intake(args.api_url.rstrip("/"), intake_id, args.token, iap_token)
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
