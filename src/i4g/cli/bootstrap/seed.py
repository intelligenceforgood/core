"""Enqueue a sample dossier plan and static review cases into the project's stores.

This module backs `i4g bootstrap seed-sample` and static data loading.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from i4g.reports.bundle_builder import DossierCandidate, DossierPlan
from i4g.settings import get_settings
from i4g.store.dossier_queue_store import DossierQueueStore
from i4g.api.cases import CASES_RESPONSE
from i4g.services.factories import build_review_store, build_structured_store
from i4g.store.schema import ScamRecord


def seed_sample_dossier() -> int:
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
            "exports": {
                "pdf_path": str(artifacts_dir / f"{plan_id}.pdf"),
                "html_path": str(artifacts_dir / f"{plan_id}.html"),
            },
            "template_render": {"path": str(artifacts_dir / f"{plan_id}.md")},
        }
        manifest_path.write_text(json.dumps(manifest_payload))
        (artifacts_dir / f"{plan_id}.pdf").write_text("pdf-bytes")
        (artifacts_dir / f"{plan_id}.md").write_text("# Pilot Dossier")
        sig = {"algorithm": "sha256", "generated_at": datetime.now(timezone.utc).isoformat(), "artifacts": []}
        (artifacts_dir / f"{plan_id}.signatures.json").write_text(json.dumps(sig))

    store = DossierQueueStore()  # unified class; uses default session from settings
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


def seed_static_review_cases() -> None:
    """Populate ReviewStore and StructuredStore with static mock cases from API definitions."""
    review_store = build_review_store()
    struct_store = build_structured_store()
    settings = get_settings()

    print(f"Seeding static cases into ReviewStore...")

    # Ensure artifacts directory for mocks
    root_dir = (
        Path(__file__).resolve().parents[4]
    )  # Adjust based on file location: src/i4g/cli/bootstrap/seed.py -> core root
    fixtures_dir = root_dir / "docker" / "fixtures" / "mock"
    mock_artifacts_dir = Path(settings.data_dir) / "artifacts" / "mock"
    mock_artifacts_dir.mkdir(parents=True, exist_ok=True)

    # Copy files from fixtures if present
    if fixtures_dir.exists():
        import shutil

        for fixture in fixtures_dir.glob("*"):
            shutil.copy(fixture, mock_artifacts_dir / fixture.name)
    else:
        # Fallback generation only if fixtures missing (e.g. lean install)
        print("Warning: Mock fixtures not found, generating minimal placeholders.")
        minimal_pdf = (
            b"%PDF-1.7\n"
            b"1 0 obj\n<</Type/Catalog/Pages 2 0 R>>\nendobj\n"
            b"2 0 obj\n<</Type/Pages/Kids[3 0 R]/Count 1>>\nendobj\n"
            b"3 0 obj\n<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Resources<<>>>>\nendobj\n"
            b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000052 00000 n \n0000000101 00000 n \n"
            b"trailer\n<</Size 4/Root 1 0 R>>\n"
            b"startxref\n178\n%%EOF\n"
        )
        (mock_artifacts_dir / "doc1.pdf").write_bytes(minimal_pdf)
        (mock_artifacts_dir / "img1.png").write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )

    for case_data in CASES_RESPONSE["cases"]:
        case_id = case_data["id"]

        # Check if exists
        existing_rev = review_store.get_cases([case_id])
        if existing_rev:
            print(f"Skipping {case_id} (already exists)")
            continue

        print(f"Upserting {case_id}...")

        # --- Structured Record (Content) ---
        # Derive entities for graph
        entities = {
            "person": ["Subject A", "Subject B"],
            "account": ["Account 123", "Account 456"],
            "transaction": ["Txn 777", "Txn 888"],
        }

        # Match logic from seed_cases.py
        files_meta = []
        if case_id == "case-482":
            files_meta = [
                {
                    "name": "Suspicious Transaction Report.pdf",
                    "type": "document",
                    "url": "/api/artifacts/mock/doc1.pdf",
                    "size": "1.2MB",
                },
                {
                    "name": "Check Screenshot.png",
                    "type": "image",
                    "url": "/api/artifacts/mock/img1.png",
                    "size": "450KB",
                },
            ]

        props = {
            "title": case_data["title"],
            "progress": case_data.get("progress"),
            "dueAt": case_data.get("dueAt"),
            "queue": case_data.get("queue"),
            "files": files_meta,
        }

        record = ScamRecord(
            case_id=case_id,
            text=f"INVESTIGATION REPORT: {case_data['title']}.\n\nThis case involves potential {case_data.get('priority')} priority activity. The subject has been flagged in queue '{case_data.get('queue')}'.\n\nAutomated extraction found multiple entities.",
            entities=entities,
            classification=case_data.get("tags", ["unknown"])[0] if case_data.get("tags") else "unknown",
            confidence=0.85,
            classification_result={"label": "fraud", "score": 0.85},
            tags=case_data.get("tags", []),
            created_at=datetime.now(timezone.utc),
            metadata=props,
        )

        struct_store.upsert_record(record)

        # --- Review Queue (State) ---
        review_id = review_store.enqueue_case(
            case_id=case_id,
            priority=case_data["priority"],
            tags=case_data.get("tags", []),
            classification_result=record.classification_result,
        )

        # Update status if present
        target_status = case_data.get("status")
        if target_status:
            review_store.update_status(review_id, status=target_status, notes="Seeded static mock case")
