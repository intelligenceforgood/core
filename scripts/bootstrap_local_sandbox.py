#!/usr/bin/env python
"""Bootstrap helper for the local i4g sandbox environment.

This script orchestrates the existing developer utilities found in docs/dev_guide.md to
regenerate sample data (bundles, screenshots, indexes, review cases) so the local profile
(`I4G_ENV=local`) has realistic fixtures without manual command juggling.

Usage:
    python scripts/bootstrap_local_sandbox.py [--skip-ocr] [--skip-vector] [--reset]
                                              [--bundle-uri PATH] [--dry-run]
                                              [--verify-only] [--report-dir DIR]

Options:
    --skip-ocr:     Do not regenerate synthetic chat screenshots or run OCR.
    --skip-vector:  Skip rebuilding vector/structured demo stores; useful when only review
                    cases need refreshing.
    --reset:        Delete derived artifacts (chat_screens, OCR output, SQLite DB, vector store)
                    before regenerating.
    --bundle-uri:   Path or URI to a bundle JSONL to place in data/bundles (local path preferred).
    --dry-run:      Print the planned steps and exit without mutating disk.
    --verify-only:  Skip generation and only run verification/report.
    --report-dir:   Destination directory for verification reports (default: data/reports).

Prerequisites:
    - Conda/venv with project dependencies installed.
    - Ollama running locally if summarization stages are executed later.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
DATA_DIR = ROOT / "data"
BUNDLES_DIR = DATA_DIR / "bundles"
CHAT_SCREENS_DIR = DATA_DIR / "chat_screens"
OCR_OUTPUT = DATA_DIR / "ocr_output.json"
SEMANTIC_OUTPUT = DATA_DIR / "entities_semantic.json"
MANUAL_DEMO_DIR = DATA_DIR / "manual_demo"
CHROMA_DIR = DATA_DIR / "chroma_store"
SQLITE_DB = DATA_DIR / "i4g_store.db"
REPORTS_DIR = DATA_DIR / "reports"
PILOT_CASES_PATH = MANUAL_DEMO_DIR / "dossier_pilot_cases.json"

DEFAULT_PILOT_CASES = [
    {
        "case_id": "dossier-pilot-001",
        "text": (
            'Victim met "Alex" on social media, was convinced to move retirement savings into a sham'
            " staking pool and wired funds to an exchange wallet controlled by the actor."
        ),
        "classification": "romance_investment",
        "confidence": 0.93,
        "loss_amount_usd": 185000,
        "jurisdiction": "US-CA",
        "victim_country": "US",
        "offender_country": "NG",
        "accepted_at": "2025-11-28T18:45:00Z",
        "entities": {
            "emails": ["finance@stellar-bonds.co"],
            "crypto_wallets": ["bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh"],
            "phone_numbers": ["+14155550127"],
        },
        "metadata": {
            "loss_currency": "USD",
            "intake_source": "northern-ca-fiu-2024Q4",
            "summary": "High-dollar romance funnel leveraging fake staking dashboards.",
        },
        "dataset": "dossier-pilot",
        "notes": "High priority given LEA interest in the rom-invest pattern.",
    },
    {
        "case_id": "dossier-pilot-002",
        "text": (
            "Shell merchant SwiftCart Pay intercepted ACH settlements and rerouted them through a"
            " US correspondent account before laundering via MX fintech partners."
        ),
        "classification": "merchant_fraud",
        "confidence": 0.9,
        "loss_amount_usd": 76000,
        "jurisdiction": "US-TX",
        "victim_country": "US",
        "offender_country": "MX",
        "accepted_at": "2025-11-30T14:20:00Z",
        "entities": {
            "bank_accounts": ["021000021-99118822"],
            "emails": ["support@swiftcart-pay.com"],
            "urls": ["https://swiftcart-pay.com/settlements"],
        },
        "metadata": {
            "loss_currency": "USD",
            "sector": "ecommerce",
            "summary": "Merchant impersonation with mule-controlled correspondent account.",
        },
        "dataset": "dossier-pilot",
        "notes": "Useful for showcasing ACH + mule indicators in a single dossier.",
    },
    {
        "case_id": "dossier-pilot-003",
        "text": (
            'Telegram pump group "Phoenix Quant" raised BTC from UK victims and disappeared after'
            " promising weekly 20% returns; funds moved through UAE OTC brokers."
        ),
        "classification": "crypto_rugpull",
        "confidence": 0.92,
        "loss_amount_usd": 310000,
        "jurisdiction": "GB-LND",
        "victim_country": "GB",
        "offender_country": "AE",
        "accepted_at": "2025-12-01T09:05:00Z",
        "entities": {
            "telegram_handles": ["@phoenix_quant"],
            "emails": ["ops@phoenixquant.ai"],
            "crypto_wallets": ["3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"],
        },
        "metadata": {
            "loss_currency": "GBP",
            "summary": "Cross-border rug pull routed through UAE OTC brokers.",
            "intake_source": "uk-ncaa-2025W03",
        },
        "dataset": "dossier-pilot",
        "notes": "Demonstrates cross-border requirement hitting Europe to Gulf corridor.",
    },
]


def run(cmd: list[str], *, cwd: Path | None = None) -> None:
    """Execute a command, streaming stdout/stderr."""

    print("→", " ".join(cmd))
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    pythonpath_parts = [str(SRC_DIR)]
    if existing_pythonpath:
        pythonpath_parts.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
    subprocess.run(cmd, cwd=cwd or ROOT, check=True, env=env)


def reset_artifacts(skip_ocr: bool, skip_vector: bool) -> None:
    """Remove generated artifacts so the sandbox refreshes cleanly."""

    if not skip_ocr:
        shutil.rmtree(CHAT_SCREENS_DIR, ignore_errors=True)
        if OCR_OUTPUT.exists():
            OCR_OUTPUT.unlink()
    if SEMANTIC_OUTPUT.exists():
        SEMANTIC_OUTPUT.unlink()
    if not skip_vector:
        shutil.rmtree(MANUAL_DEMO_DIR, ignore_errors=True)
        shutil.rmtree(CHROMA_DIR, ignore_errors=True)
        if SQLITE_DB.exists():
            SQLITE_DB.unlink()
    shutil.rmtree(REPORTS_DIR, ignore_errors=True)


def ensure_dirs() -> None:
    """Create data directories expected by downstream scripts."""

    for path in (BUNDLES_DIR, CHAT_SCREENS_DIR, REPORTS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def build_bundles() -> None:
    run(
        [
            sys.executable,
            "tests/adhoc/build_scam_bundle.py",
            "--outdir",
            str(BUNDLES_DIR),
            "--chunk_chars",
            "800",
        ]
    )


def synthesize_screens() -> Path:
    bundles = sorted(BUNDLES_DIR.glob("*.jsonl"))
    if not bundles:
        raise RuntimeError("No bundle JSONL files found in data/bundles; rerun build step.")
    bundle = bundles[0]
    run(
        [
            sys.executable,
            "tests/adhoc/synthesize_chat_screenshots.py",
            "--input",
            str(bundle),
            "--limit",
            "20",
        ]
    )
    return bundle


def run_ocr() -> None:
    from i4g.cli import extract_tasks

    exit_code = extract_tasks.ocr(SimpleNamespace(input=CHAT_SCREENS_DIR, output=OCR_OUTPUT))
    if exit_code:
        raise RuntimeError(f"OCR failed with exit code {exit_code}")


def run_semantic_extraction() -> None:
    from i4g.cli import extract_tasks

    exit_code = extract_tasks.semantic(SimpleNamespace(input=OCR_OUTPUT, output=SEMANTIC_OUTPUT, model="llama3.1"))
    if exit_code:
        raise RuntimeError(f"Semantic extraction failed with exit code {exit_code}")


def rebuild_manual_demo() -> None:
    run(
        [
            sys.executable,
            "tests/adhoc/manual_ingest_demo.py",
            "--structured-db",
            str(SQLITE_DB),
            "--vector-dir",
            str(CHROMA_DIR),
        ]
    )


def ensure_pilot_cases_file() -> None:
    if PILOT_CASES_PATH.exists():
        return
    PILOT_CASES_PATH.parent.mkdir(parents=True, exist_ok=True)
    PILOT_CASES_PATH.write_text(json.dumps(DEFAULT_PILOT_CASES, indent=2))
    print(f"🗂️  Seeded pilot cases config at {PILOT_CASES_PATH}")


def seed_review_cases() -> None:
    run(
        [
            sys.executable,
            "tests/adhoc/synthesize_review_cases.py",
            "--reset",
            "--queued",
            "5",
            "--in-review",
            "2",
            "--accepted",
            "1",
            "--rejected",
            "1",
        ]
    )


def apply_migrations() -> None:
    """Apply Alembic migrations before seeding structured data."""

    run(
        [
            sys.executable,
            "-m",
            "alembic",
            "upgrade",
            "head",
        ]
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap local sandbox data")
    parser.add_argument("--skip-ocr", action="store_true", help="Skip generating chat screenshots and OCR")
    parser.add_argument("--skip-vector", action="store_true", help="Skip rebuilding vector/structured demo stores")
    parser.add_argument("--reset", action="store_true", help="Remove derived artifacts before regenerating")
    parser.add_argument(
        "--bundle-uri",
        type=str,
        default=None,
        help="Path or URI to a bundle JSONL to place in data/bundles (local paths preferred).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print planned actions and exit")
    parser.add_argument("--verify-only", action="store_true", help="Only run verification/report")
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=REPORTS_DIR,
        help="Destination directory for verification reports (default: data/reports)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow running when I4G_ENV is not local (use with caution).",
    )
    parser.add_argument(
        "--smoke-search",
        action="store_true",
        help="Run search smoke (requires vertex settings).",
    )
    parser.add_argument(
        "--smoke-dossiers",
        action="store_true",
        help="Run dossier signature verification smoke (requires API + token).",
    )
    parser.add_argument(
        "--search-project",
        help="Vertex project for search smoke (defaults to settings).",
    )
    parser.add_argument(
        "--search-location",
        default="global",
        help="Vertex location for search smoke (default: global).",
    )
    parser.add_argument(
        "--search-data-store-id",
        help="Vertex data store id for search smoke (required when --smoke-search).",
    )
    parser.add_argument(
        "--search-serving-config-id",
        default="default_search",
        help="Vertex serving config id for search smoke (default: default_search).",
    )
    parser.add_argument(
        "--search-query",
        default="wallet address verification",
        help="Query string for search smoke (default: wallet address verification).",
    )
    parser.add_argument(
        "--search-page-size",
        type=int,
        default=5,
        help="Page size for search smoke results (default: 5).",
    )
    parser.add_argument(
        "--smoke-api-url",
        default=os.getenv("I4G_SMOKE_API_URL", "http://127.0.0.1:8000"),
        help="API base URL for dossier smoke (default: http://127.0.0.1:8000).",
    )
    parser.add_argument(
        "--smoke-token",
        default=os.getenv("I4G_SMOKE_TOKEN", "dev-analyst-token"),
        help="API token for dossier smoke (default: env or dev-analyst-token).",
    )
    parser.add_argument(
        "--smoke-dossier-status",
        default="completed",
        help="Dossier queue status filter for smoke (default: completed).",
    )
    parser.add_argument(
        "--smoke-dossier-limit",
        type=int,
        default=5,
        help="Maximum dossiers to inspect during smoke (default: 5).",
    )
    parser.add_argument(
        "--smoke-dossier-plan-id",
        help="Optional specific dossier plan_id to verify during smoke.",
    )
    return parser.parse_args(argv)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stage_bundle(bundle_uri: str | None) -> Path | None:
    """Place a provided bundle JSONL into data/bundles; local path only for now."""

    if not bundle_uri:
        return None

    candidate = Path(bundle_uri)
    if not candidate.exists():
        raise RuntimeError(f"bundle-uri path not found: {bundle_uri}")
    if candidate.is_dir():
        jsonls = list(candidate.glob("*.jsonl"))
        if not jsonls:
            raise RuntimeError(f"No JSONL files found in bundle-uri directory: {bundle_uri}")
        target = BUNDLES_DIR / jsonls[0].name
        target.write_bytes(jsonls[0].read_bytes())
        digest = _hash_file(target)
        print(f"📦 Copied bundle {jsonls[0]} -> {target} (sha256={digest})")
        return target

    if candidate.suffix.lower() != ".jsonl":
        raise RuntimeError("bundle-uri must point to a .jsonl file")
    target = BUNDLES_DIR / candidate.name
    target.write_bytes(candidate.read_bytes())
    digest = _hash_file(target)
    print(f"📦 Copied bundle {candidate} -> {target} (sha256={digest})")
    return target


def verify_sandbox(
    report_dir: Path,
    search_smoke: dict[str, str] | None = None,
    dossier_smoke: dict[str, str | None] | None = None,
) -> Path:
    """Run lightweight verification and emit JSON + Markdown reports."""

    report_dir.mkdir(parents=True, exist_ok=True)

    bundles = sorted(BUNDLES_DIR.glob("*.jsonl"))
    ocr_exists = OCR_OUTPUT.exists()
    vector_exists = CHROMA_DIR.exists() and any(CHROMA_DIR.iterdir())
    db_exists = SQLITE_DB.exists()
    pilot_exists = PILOT_CASES_PATH.exists()

    bundle_hashes = {str(path): _hash_file(path) for path in bundles}
    bundle_manifest_hash = None
    if bundle_hashes:
        manifest_digest = hashlib.sha256()
        for path, digest in sorted(bundle_hashes.items()):
            manifest_digest.update(path.encode("utf-8"))
            manifest_digest.update(digest.encode("utf-8"))
        bundle_manifest_hash = manifest_digest.hexdigest()
    bundle_counts: dict[str, int] = {}
    for path in bundles:
        try:
            with path.open("r", encoding="utf-8") as handle:
                bundle_counts[str(path)] = sum(1 for _ in handle)
        except OSError:
            bundle_counts[str(path)] = -1

    ocr_count: int | None = None
    if ocr_exists:
        try:
            payload = json.loads(OCR_OUTPUT.read_text())
            if isinstance(payload, list):
                ocr_count = len(payload)
        except json.JSONDecodeError:
            ocr_count = -1

    db_counts: dict[str, int] | None = None
    ingestion_run_summary: dict[str, str | int] | None = None
    if db_exists:
        try:
            with sqlite3.connect(SQLITE_DB) as conn:
                cur = conn.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
                db_counts = {}
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
            db_counts = None

    report = {
        "bundles": [str(path) for path in bundles],
        "bundle_count": len(bundles),
        "bundle_hashes": bundle_hashes,
        "bundle_manifest_hash": bundle_manifest_hash,
        "bundle_record_counts": bundle_counts,
        "ocr_output": str(OCR_OUTPUT) if ocr_exists else None,
        "ocr_record_count": ocr_count,
        "vector_store_present": vector_exists,
        "sqlite_db_present": db_exists,
        "sqlite_table_counts": db_counts,
        "pilot_cases_present": pilot_exists,
    }
    if ingestion_run_summary:
        report["ingestion_run_summary"] = ingestion_run_summary
    if search_smoke:
        report["search_smoke"] = search_smoke
    if bundle_manifest_hash:
        print(f"Bundle manifest sha256: {bundle_manifest_hash}")
    if dossier_smoke:
        report["dossier_smoke"] = dossier_smoke

    json_path = report_dir / "bootstrap_verify.json"
    md_path = report_dir / "bootstrap_verify.md"

    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    md_lines = ["# Local Bootstrap Verification", ""]
    md_lines.append(f"- Bundles: {report['bundle_count']} ({', '.join(report['bundles']) or 'none'})")
    if bundle_hashes:
        for path, digest in bundle_hashes.items():
            md_lines.append(f"  - {path}: sha256={digest}")
    if bundle_manifest_hash:
        md_lines.append(f"- Bundle manifest hash: {bundle_manifest_hash}")
    if bundle_counts:
        for path, count in bundle_counts.items():
            md_lines.append(f"  - {path}: records={count}")
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
        md_lines.append(f"- {search_smoke.get('status')}: {search_smoke.get('message')}")
    if dossier_smoke:
        md_lines.append("")
        md_lines.append("## Dossier smoke")
        md_lines.append(f"- {dossier_smoke.get('status')}: {dossier_smoke.get('message')}")
        if dossier_smoke.get("plan_id"):
            md_lines.append(f"- plan_id: {dossier_smoke.get('plan_id')}")
        if dossier_smoke.get("manifest_path"):
            md_lines.append(f"- manifest: {dossier_smoke.get('manifest_path')}")
        if dossier_smoke.get("signature_path"):
            md_lines.append(f"- signature: {dossier_smoke.get('signature_path')}")
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print(f"🧾 Verification reports written to {report_dir}")
    return json_path


def _run_search_smoke(args: argparse.Namespace) -> dict[str, str]:
    """Run a lightweight Vertex search smoke when requested."""

    if not args.smoke_search:
        return {"status": "skipped", "message": "Search smoke disabled."}

    project = args.search_project or os.getenv("I4G_VECTOR__VERTEX_AI_PROJECT") or os.getenv("I4G_PROJECT")
    data_store = args.search_data_store_id or os.getenv("I4G_VECTOR__VERTEX_AI_DATA_STORE")
    serving_config = args.search_serving_config_id or os.getenv("I4G_VECTOR__VERTEX_AI_SERVING_CONFIG")
    location = args.search_location or os.getenv("I4G_VECTOR__VERTEX_AI_LOCATION") or "global"

    if not project or not data_store or not serving_config:
        return {
            "status": "skipped",
            "message": "Missing search configuration (project/data_store/serving_config).",
        }

    try:
        from i4g.cli import smoke

        search_args = SimpleNamespace(
            project=project,
            location=location,
            data_store_id=data_store,
            serving_config_id=serving_config,
            query=args.search_query,
            page_size=args.search_page_size,
        )
        smoke.vertex_search_smoke(search_args)
    except SystemExit as exc:  # pragma: no cover - subprocess failure path
        return {"status": "failed", "message": str(exc)}
    except Exception as exc:  # pragma: no cover - safety net
        return {"status": "failed", "message": str(exc)}

    return {"status": "success", "message": "Vertex search returned results."}


def _run_dossier_smoke(args: argparse.Namespace) -> dict[str, str | None]:
    """Run dossier signature verification smoke when requested."""

    if not args.smoke_dossiers:
        return {"status": "skipped", "message": "Dossier smoke disabled."}

    try:
        from scripts import smoke_dossiers

        smoke_args = SimpleNamespace(
            api_url=args.smoke_api_url,
            token=args.smoke_token,
            status=args.smoke_dossier_status,
            limit=args.smoke_dossier_limit,
            plan_id=args.smoke_dossier_plan_id,
        )
        result = smoke_dossiers.run_smoke(smoke_args)
    except Exception as exc:  # pragma: no cover - CLI/network boundary safety net
        return {"status": "failed", "message": str(exc)}

    return {
        "status": "success",
        "message": "Dossier verification passed.",
        "plan_id": str(result.plan_id) if getattr(result, "plan_id", None) else None,
        "manifest_path": str(result.manifest_path) if getattr(result, "manifest_path", None) else None,
        "signature_path": str(result.signature_path) if getattr(result, "signature_path", None) else None,
    }


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    env_val = os.environ.get("I4G_ENV", "")
    if env_val != "local" and not args.force:
        print(f"❌ Refusing to run: I4G_ENV={env_val!r} (expected 'local'). Pass --force to override.")
        return
    if env_val != "local":
        print(f"⚠️  Running with I4G_ENV={env_val!r}; proceeding due to --force.")

    if args.dry_run:
        print(
            "[dry-run] Would reset=%s skip_ocr=%s skip_vector=%s bundle_uri=%s verify_only=%s"
            % (args.reset, args.skip_ocr, args.skip_vector, args.bundle_uri, args.verify_only)
        )
        return

    ensure_dirs()

    if args.reset:
        reset_artifacts(skip_ocr=args.skip_ocr, skip_vector=args.skip_vector)

    if args.bundle_uri:
        _stage_bundle(args.bundle_uri)

    if args.verify_only:
        search_smoke = _run_search_smoke(args)
        if search_smoke.get("status") == "failed":
            raise SystemExit(search_smoke.get("message"))
        dossier_smoke = _run_dossier_smoke(args)
        if dossier_smoke.get("status") == "failed":
            raise SystemExit(dossier_smoke.get("message"))
        verify_sandbox(args.report_dir, search_smoke, dossier_smoke)
        return

    apply_migrations()

    if not BUNDLES_DIR.exists() or not any(BUNDLES_DIR.glob("*.jsonl")):
        build_bundles()

    tesseract_available = shutil.which("tesseract") is not None
    if not args.skip_ocr:
        if not tesseract_available:
            print(
                "⚠️  Tesseract not found on PATH; skipping OCR and semantic extraction. "
                "Install it or rerun with --skip-ocr."
            )
        else:
            synthesize_screens()
            run_ocr()
            run_semantic_extraction()
    else:
        print("⚠️  Skipping OCR pipeline; existing artifacts will be reused if present.")

    if not args.skip_vector:
        rebuild_manual_demo()
    else:
        print("⚠️  Skipping vector/structured demo rebuild; existing stores assumed valid.")

    ensure_pilot_cases_file()

    seed_review_cases()

    search_smoke = _run_search_smoke(args)
    if search_smoke.get("status") == "failed":
        raise SystemExit(search_smoke.get("message"))
    dossier_smoke = _run_dossier_smoke(args)
    if dossier_smoke.get("status") == "failed":
        raise SystemExit(dossier_smoke.get("message"))
    verify_sandbox(args.report_dir, search_smoke, dossier_smoke)

    print("✅ Local sandbox refreshed. Data directory:", DATA_DIR)


if __name__ == "__main__":
    main()
