"""Verification logic for the local sandbox."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from i4g.cli.utils import hash_file
from i4g.cli.bootstrap.common import (
    DossierSmokeResult,
    SearchSmokeResult,
    VerificationReport,
)

from .constants import (
    BUNDLES_DIR,
    CHROMA_DIR,
    OCR_OUTPUT,
    PILOT_CASES_PATH,
    SQLITE_DB,
)


def verify_sandbox(
    report_dir: Path,
    search_smoke: SearchSmokeResult | None = None,
    dossier_smoke: DossierSmokeResult | None = None,
) -> Path:
    """Run lightweight verification and emit JSON + Markdown reports."""

    report_dir.mkdir(parents=True, exist_ok=True)

    bundles = sorted(BUNDLES_DIR.glob("*.jsonl"))
    ocr_exists = OCR_OUTPUT.exists()
    vector_exists = CHROMA_DIR.exists() and any(CHROMA_DIR.iterdir())
    db_exists = SQLITE_DB.exists()
    pilot_exists = PILOT_CASES_PATH.exists()

    bundle_hashes = {str(path.name): hash_file(path) for path in bundles}

    bundle_counts: dict[str, int] = {}
    for path in bundles:
        try:
            with path.open("r", encoding="utf-8") as handle:
                bundle_counts[str(path.name)] = sum(1 for _ in handle)
        except OSError:
            bundle_counts[str(path.name)] = -1

    ocr_count: int | None = None
    if ocr_exists:
        try:
            with OCR_OUTPUT.open("r", encoding="utf-8") as handle:
                ocr_count = sum(1 for _ in handle)
        except OSError:
            ocr_count = -1

    db_counts: dict[str, int] = {}
    ingestion_run_summary: dict[str, str | int] | None = None
    if db_exists:
        try:
            with sqlite3.connect(SQLITE_DB) as conn:
                cur = conn.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
                for (table_name,) in cur.fetchall():
                    try:
                        cur.execute(f"SELECT COUNT(*) FROM {table_name}")
                        db_counts[table_name] = int(cur.fetchone()[0])
                    except sqlite3.DatabaseError:
                        db_counts[table_name] = -1
                if "ingestion_run" in db_counts:
                    try:
                        cur.execute("SELECT COUNT(*) as cnt, MAX(started_at) as last_started FROM ingestion_run")
                        cnt, last_started = cur.fetchone()
                        ingestion_run_summary = {
                            "count": int(cnt or 0),
                            "last_started_at": str(last_started) if last_started is not None else None,
                        }
                    except sqlite3.DatabaseError:
                        ingestion_run_summary = {"count": -1, "last_started_at": None}
        except sqlite3.DatabaseError:
            pass

    # Construct VerificationReport
    storage_stats = {
        "primary_db": db_counts,
        "vector_store": {"present": vector_exists, "path": str(CHROMA_DIR)},
        "ocr": {"present": ocr_exists, "count": ocr_count, "path": str(OCR_OUTPUT)},
        "pilot_cases": {"present": pilot_exists, "path": str(PILOT_CASES_PATH)},
    }
    if ingestion_run_summary:
        storage_stats["ingestion_run"] = ingestion_run_summary

    smoke_tests = {}
    if search_smoke:
        smoke_tests["search"] = vars(search_smoke)
    if dossier_smoke:
        smoke_tests["dossier"] = vars(dossier_smoke)

    report = VerificationReport(
        environment="local",
        timestamp=datetime.now(timezone.utc).isoformat(),
        bundles={
            "files": [str(p.name) for p in bundles],
            "hashes": bundle_hashes,
            "counts": bundle_counts,
        },
        storage=storage_stats,
        smoke_tests=smoke_tests,
        errors=[],
    )

    json_path = report_dir / "verify.json"
    md_path = report_dir / "verify.md"

    json_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    md_lines = ["# Local Bootstrap Verification", ""]
    md_lines.append(f"- Bundles: {len(bundles)} ({', '.join(report.bundles['files']) or 'none'})")
    if bundle_hashes:
        for name, digest in bundle_hashes.items():
            md_lines.append(f"  - {name}: sha256={digest}")
    if bundle_counts:
        for name, count in bundle_counts.items():
            md_lines.append(f"  - {name}: records={count}")

    md_lines.append(f"- OCR output present: {ocr_exists}")
    if ocr_count is not None:
        md_lines.append(f"  - OCR records: {ocr_count}")

    md_lines.append(f"- Vector store present: {vector_exists}")
    md_lines.append(f"- SQLite DB present: {db_exists}")

    if db_counts:
        for table, count in db_counts.items():
            md_lines.append(f"  - {table}: rows={count}")

    if ingestion_run_summary:
        md_lines.append("- Ingestion runs:")
        md_lines.append(f"  - count: {ingestion_run_summary.get('count')}")
        md_lines.append(f"  - last_started_at: {ingestion_run_summary.get('last_started_at')}")

    md_lines.append(f"- Pilot cases present: {pilot_exists}")

    if search_smoke:
        md_lines.append("")
        md_lines.append("## Search smoke")
        md_lines.append(f"- {search_smoke.status}: {search_smoke.message}")
    if dossier_smoke:
        md_lines.append("")
        md_lines.append("## Dossier smoke")
        md_lines.append(f"- {dossier_smoke.status}: {dossier_smoke.message}")
        if dossier_smoke.plan_id:
            md_lines.append(f"- plan_id: {dossier_smoke.plan_id}")
        if dossier_smoke.manifest_path:
            md_lines.append(f"- manifest: {dossier_smoke.manifest_path}")
        if dossier_smoke.signature_path:
            md_lines.append(f"- signature: {dossier_smoke.signature_path}")

    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print(f"🧾 Verification reports written to {report_dir}")
    return json_path


__all__ = ["verify_sandbox"]
