#!/usr/bin/env python3
"""Enqueue a sample dossier plan into the project's DossierQueueStore DB.

This script writes a DossierPlan and marks it as completed so the running server can
discover it via `/reports/dossiers` endpoints.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from decimal import Decimal

from i4g.reports.bundle_builder import DossierCandidate, DossierPlan
from i4g.store.dossier_queue_store import DossierQueueStore
from i4g.settings import get_settings


def main() -> int:
    settings = get_settings()
    data_dir = Path(settings.data_dir)
    artifacts_dir = data_dir / "reports" / "dossiers"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    # Create trivial artifacts if not present
    plan_id = "pilot-plan-001"
    manifest_path = artifacts_dir / f"{plan_id}.json"
    if not manifest_path.exists():
        manifest_payload = {
            "plan_id": plan_id,
            "signature_manifest": {"path": str(artifacts_dir / f"{plan_id}.signatures.json")},
            "exports": {"pdf_path": str(artifacts_dir / f"{plan_id}.pdf"), "html_path": str(artifacts_dir / f"{plan_id}.html")},
            "template_render": {"path": str(artifacts_dir / f"{plan_id}.md")},
        }
        manifest_path.write_text(json.dumps(manifest_payload))
        (artifacts_dir / f"{plan_id}.pdf").write_text("pdf-bytes")
        (artifacts_dir / f"{plan_id}.md").write_text("# Pilot Dossier")
        sig = {"algorithm": "sha256", "generated_at": datetime.now(timezone.utc).isoformat(), "artifacts": []}
        (artifacts_dir / f"{plan_id}.signatures.json").write_text(json.dumps(sig))

    store = DossierQueueStore()  # uses default sqlite_path from settings
    candidate = DossierCandidate(
        case_id="case-1",
        loss_amount_usd=Decimal("125000"),
        accepted_at=datetime(2025, 12, 1, tzinfo=timezone.utc),
        jurisdiction="US-CA",
        cross_border=True,
        primary_entities=("wallet:test",),
    )
    plan = DossierPlan(
        plan_id=plan_id,
        jurisdiction_key="US-CA",
        created_at=datetime(2025, 12, 2, tzinfo=timezone.utc),
        total_loss_usd=Decimal("125000"),
        cases=[candidate],
        bundle_reason="pilot-run",
        cross_border=True,
        shared_drive_parent_id="drive-folder",
    )
    store.enqueue_plan(plan)
    store.mark_complete(plan.plan_id)
    print("Inserted plan", plan_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
