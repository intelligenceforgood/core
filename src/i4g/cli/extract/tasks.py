"""Extraction/OCR helpers formerly in scripts/*."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from tqdm import tqdm

from i4g.api import reports as reports_api
from i4g.api.app import create_app
from i4g.cli.utils import iter_jsonl, write_jsonl
from i4g.extraction.ner_rules import extract_entities
from i4g.extraction.semantic_ner import build_llm, extract_semantic_entities
from i4g.ocr.tesseract import batch_extract_text
from i4g.reports.bundle_builder import DossierCandidate, DossierPlan
from i4g.store.dossier_queue_store import DossierQueueStore


def ocr(args: object) -> int:
    input_path = Path(args.input)
    output_path = Path(args.output)
    output_path.parent.mkdir(exist_ok=True)

    results = batch_extract_text(str(input_path))
    write_jsonl(output_path, results)
    print(f"✅ OCR complete. Results saved to {output_path}")
    return 0


def extraction(args: object) -> int:
    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        print("❌ OCR output not found. Run i4g extract ocr first.")
        return 1

    ocr_results = list(iter_jsonl(input_path))

    structured: list[dict[str, object]] = []
    for item in tqdm(ocr_results, desc="Extracting entities"):
        text = item.get("text", "")
        entities = extract_entities(text)
        structured.append({"file": item.get("file"), "entities": entities})

    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(output_path, structured)
    print(f"✅ Entity extraction complete. Saved to {output_path}")
    return 0


def semantic(args: object) -> int:
    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        print("❌ OCR output not found. Run i4g extract ocr first.")
        return 1

    llm = build_llm(model=args.model)
    ocr_results = list(iter_jsonl(input_path))

    output: list[dict[str, object]] = []
    for item in tqdm(ocr_results, desc="Semantic extraction"):
        text = item.get("text", "")
        if not str(text).strip():
            output.append({"file": item.get("file"), "semantic_entities": {}})
            continue

        entities = extract_semantic_entities(text, llm)
        output.append({"file": item.get("file"), "semantic_entities": entities})

    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(output_path, output)
    print(f"✅ Semantic extraction saved to {output_path}")
    return 0


def lea_pilot(args: object) -> int:
    import hashlib
    import tempfile
    from datetime import datetime, timezone

    def _sha256_hex(path: Path) -> str:
        hasher = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def create_sample_plan(artifact_dir: Path) -> DossierPlan:
        candidate = DossierCandidate(
            case_id="case-1",
            loss_amount_usd=125_000,
            accepted_at=datetime(2025, 12, 1, tzinfo=timezone.utc),
            jurisdiction="US-CA",
            cross_border=True,
            primary_entities=("wallet:test",),
        )
        plan = DossierPlan(
            plan_id="pilot-plan-001",
            jurisdiction_key="US-CA",
            created_at=datetime(2025, 12, 2, tzinfo=timezone.utc),
            total_loss_usd=125_000,
            cases=[candidate],
            bundle_reason="pilot-run",
            cross_border=True,
            shared_drive_parent_id="drive-folder",
        )
        manifest_path = artifact_dir / f"{plan.plan_id}.json"
        manifest_payload = {
            "plan_id": plan.plan_id,
            "signature_manifest": {"path": str(artifact_dir / f"{plan.plan_id}.signatures.json")},
            "assets": {"timeline_chart": "chart.png"},
            "exports": {
                "pdf_path": str(artifact_dir / f"{plan.plan_id}.pdf"),
                "html_path": str(artifact_dir / f"{plan.plan_id}.html"),
            },
            "template_render": {"path": str(artifact_dir / f"{plan.plan_id}.md")},
        }
        manifest_path.write_text(json.dumps(manifest_payload))
        pdf = artifact_dir / f"{plan.plan_id}.pdf"
        pdf.write_bytes(b"pdf-bytes")
        md = artifact_dir / f"{plan.plan_id}.md"
        md.write_text("# Pilot Dossier\n\nThis is a pilot dossier.")
        sig_path = artifact_dir / f"{plan.plan_id}.signatures.json"
        sig = {
            "algorithm": "sha256",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "artifacts": [
                {
                    "label": "manifest",
                    "path": str(manifest_path),
                    "size_bytes": manifest_path.stat().st_size,
                    "hash": _sha256_hex(manifest_path),
                },
                {"label": "pdf", "path": str(pdf), "size_bytes": pdf.stat().st_size, "hash": _sha256_hex(pdf)},
                {"label": "markdown", "path": str(md), "size_bytes": md.stat().st_size, "hash": _sha256_hex(md)},
            ],
            "warnings": [],
        }
        sig_path.write_text(json.dumps(sig))
        return plan

    tmp_root = Path(tempfile.mkdtemp(prefix="i4g-lea-pilot-"))
    artifacts_dir = tmp_root / "reports" / "dossiers"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    queue_db = tmp_root / "dossier_queue.db"
    store = DossierQueueStore(db_path=queue_db)
    plan = create_sample_plan(artifacts_dir)
    store.enqueue_plan(plan)
    store.mark_complete(plan.plan_id, warnings=[])

    reports_api.build_dossier_queue_store = lambda: store  # type: ignore[assignment]
    reports_api.ARTIFACTS_DIR = artifacts_dir  # type: ignore[assignment]

    app = create_app()
    client = TestClient(app)

    response = client.get("/reports/dossiers", params={"status": "completed", "include_manifest": True})
    if response.status_code != 200:
        print("LIST FAILED:", response.status_code, response.text)
        return 2
    items = response.json().get("items") or []
    print("Listed items:", len(items))

    verify_resp = client.post(f"/reports/dossiers/{plan.plan_id}/verify")
    if verify_resp.status_code != 200:
        print("VERIFY FAILED:", verify_resp.status_code, verify_resp.text)
        return 3
    print("VERIFY OK:", verify_resp.json())
    return 0


__all__ = ["ocr", "extraction", "semantic", "lea_pilot"]
