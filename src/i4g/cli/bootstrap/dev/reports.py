"""Report generation for dev bootstrap runs."""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone

from i4g.cli.bootstrap.common import DossierSmokeResult, SearchSmokeResult, SmokeResult

from .constants import JobResult
from .verify import verify_cloud_state


def write_reports(
    results: list[JobResult],
    smoke_result: SmokeResult | None,
    dossier_smoke: DossierSmokeResult | None,
    search_smoke: SearchSmokeResult | None,
    args: argparse.Namespace,
) -> None:
    args.report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()

    # Gather verification state
    verification_report = verify_cloud_state(args)

    # Populate smoke tests in verification report
    if search_smoke:
        verification_report.smoke_tests["search"] = vars(search_smoke)
    if dossier_smoke:
        verification_report.smoke_tests["dossier"] = vars(dossier_smoke)

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
        "smoke": vars(smoke_result) if smoke_result else None,
        "dossier_smoke": vars(dossier_smoke) if dossier_smoke else None,
        "search_smoke": vars(search_smoke) if search_smoke else None,
        "verification": verification_report.to_dict(),
    }

    json_path = args.report_dir / "report.json"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True))

    lines = [
        f"# Dev bootstrap report ({timestamp})",
        "",
        f"Project: {args.project}",
        f"Region: {args.region}",
        f"Bundle: {args.bundle or '<none>'}",
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

    (args.report_dir / "report.md").write_text("\n".join(lines))

    # Write verify.json and verify.md using VerificationReport
    (args.report_dir / "verify.json").write_text(json.dumps(verification_report.to_dict(), indent=2, sort_keys=True))

    verify_lines = [
        f"# Dev Bootstrap Verification ({timestamp})",
        "",
        f"Project: {args.project}",
        "",
        "## Bundles",
    ]
    for name, info in verification_report.bundles.items():
        status = "\u2705" if info.get("exists") else "\u274c"
        verify_lines.append(f"- {status} {name}: {info.get('uri')}")

    verify_lines.append("")
    verify_lines.append("## Storage Stats")

    if "sqlite" in verification_report.storage:
        verify_lines.append("### SQLite (Local)")
        for k, v in verification_report.storage.get("sqlite", {}).items():
            verify_lines.append(f"- {k}: {v}")

    if "cloud_sql" in verification_report.storage:
        verify_lines.append("### Cloud SQL")
        for k, v in verification_report.storage.get("cloud_sql", {}).items():
            verify_lines.append(f"- {k}: {v}")

    verify_lines.append("### Vector Store")
    for k, v in verification_report.storage.get("vector_store", {}).items():
        verify_lines.append(f"- {k}: {v}")

    if verification_report.errors:
        verify_lines.append("")
        verify_lines.append("## Errors")
        for err in verification_report.errors:
            verify_lines.append(f"- \u274c {err}")

    (args.report_dir / "verify.md").write_text("\n".join(verify_lines))

    logging.info("Reports written to %s", args.report_dir)
