"""Bootstrap helpers for the local sandbox."""

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
from typing import Optional

import typer

from i4g.cli.utils import hash_file, stage_bundle

ROOT = Path(__file__).resolve().parents[4]
SRC_DIR = ROOT / "src"
DATA_DIR = ROOT / "data"
BUNDLES_DIR = DATA_DIR / "bundles"
CHAT_SCREENS_DIR = DATA_DIR / "chat_screens"
OCR_OUTPUT = DATA_DIR / "ocr_output.jsonl"
SEMANTIC_OUTPUT = DATA_DIR / "entities_semantic.jsonl"
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


def run(cmd: list[str], *, cwd: Path | None = None, env_overrides: dict[str, str] | None = None) -> None:
    """Execute a command, streaming stdout/stderr with PYTHONPATH set."""

    print("→", " ".join(cmd))
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    existing_pythonpath = env.get("PYTHONPATH")
    pythonpath_parts = [str(SRC_DIR)]
    if existing_pythonpath:
        pythonpath_parts.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
    subprocess = __import__("subprocess")
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


def ingest_bundles(skip_vector: bool) -> None:
    bundles = sorted(BUNDLES_DIR.glob("*.jsonl"))
    if not bundles:
        print("⚠️  No bundles found to ingest.")
        return

    print(f"🚀 Ingesting {len(bundles)} bundles...")
    for bundle in bundles:
        print(f"   → Processing {bundle.name}...")
        env = {
            "I4G_INGEST__JSONL_PATH": str(bundle),
            "I4G_INGEST__ENABLE_VECTOR": "false" if skip_vector else "true",
            "I4G_STORAGE__STRUCTURED_BACKEND": "sqlite",
            "I4G_STORAGE__SQLITE_PATH": str(SQLITE_DB),
            "I4G_INGEST__MAX_RETRIES": "0",
        }
        run([sys.executable, "-m", "i4g.worker.jobs.ingest"], env_overrides=env)


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
    from i4g.cli.extract import tasks as extract_tasks

    exit_code = extract_tasks.ocr(SimpleNamespace(input=CHAT_SCREENS_DIR, output=OCR_OUTPUT))
    if exit_code:
        raise RuntimeError(f"OCR failed with exit code {exit_code}")


def run_semantic_extraction() -> None:
    from i4g.cli.extract import tasks as extract_tasks

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

    run([sys.executable, "-m", "alembic", "upgrade", "head"])


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

    bundle_hashes = {str(path): hash_file(path) for path in bundles}
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
            with OCR_OUTPUT.open("r", encoding="utf-8") as handle:
                ocr_count = sum(1 for _ in handle)
        except OSError:
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


def run_local(
    *,
    reset: bool,
    skip_ocr: bool,
    skip_vector: bool,
    bundle_uri: Optional[str],
    dry_run: bool,
    verify_only: bool,
    report_dir: Path,
    smoke_search: bool,
    search_project: Optional[str],
    search_location: Optional[str],
    search_data_store_id: Optional[str],
    search_serving_config_id: str,
    search_query: str,
    search_page_size: int,
    smoke_dossiers: bool,
    smoke_api_url: Optional[str],
    smoke_token: Optional[str],
    smoke_dossier_status: str,
    smoke_dossier_limit: int,
    smoke_dossier_plan_id: Optional[str],
    force: bool,
) -> None:
    """Execute the local sandbox bootstrap flow."""

    env_val = os.getenv("I4G_ENV", "")
    if env_val != "local" and not force:
        print(f"❌ Refusing to run: I4G_ENV={env_val!r} (expected 'local'). Pass --force to override.")
        return
    if env_val != "local":
        print(f"⚠️  Running with I4G_ENV={env_val!r}; proceeding due to --force.")

    if dry_run:
        print(
            "[dry-run] Would reset=%s skip_ocr=%s skip_vector=%s bundle_uri=%s verify_only=%s"
            % (reset, skip_ocr, skip_vector, bundle_uri, verify_only)
        )
        return

    ensure_dirs()

    if reset:
        reset_artifacts(skip_ocr=skip_ocr, skip_vector=skip_vector)

    if bundle_uri:
        stage_bundle(bundle_uri, BUNDLES_DIR)

    args_ns = argparse.Namespace(
        smoke_search=smoke_search,
        search_project=search_project,
        search_location=search_location,
        search_data_store_id=search_data_store_id,
        search_serving_config_id=search_serving_config_id,
        search_query=search_query,
        search_page_size=search_page_size,
        smoke_dossiers=smoke_dossiers,
        smoke_api_url=smoke_api_url,
        smoke_token=smoke_token,
        smoke_dossier_status=smoke_dossier_status,
        smoke_dossier_limit=smoke_dossier_limit,
        smoke_dossier_plan_id=smoke_dossier_plan_id,
    )

    if verify_only:
        search_smoke = _run_search_smoke(args_ns)
        if search_smoke.get("status") == "failed":
            raise SystemExit(search_smoke.get("message"))
        dossier_smoke = _run_dossier_smoke(args_ns)
        if dossier_smoke.get("status") == "failed":
            raise SystemExit(dossier_smoke.get("message"))
        verify_sandbox(report_dir, search_smoke, dossier_smoke)
        return

    apply_migrations()

    if not BUNDLES_DIR.exists() or not any(BUNDLES_DIR.glob("*.jsonl")):
        build_bundles()

    ingest_bundles(skip_vector=skip_vector)

    tesseract_available = shutil.which("tesseract") is not None
    if not skip_ocr:
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

    if not skip_vector:
        rebuild_manual_demo()
    else:
        print("⚠️  Skipping vector/structured demo rebuild; existing stores assumed valid.")

    ensure_pilot_cases_file()
    seed_review_cases()

    search_smoke = _run_search_smoke(args_ns)
    if search_smoke.get("status") == "failed":
        raise SystemExit(search_smoke.get("message"))
    dossier_smoke = _run_dossier_smoke(args_ns)
    if dossier_smoke.get("status") == "failed":
        raise SystemExit(dossier_smoke.get("message"))
    verify_sandbox(report_dir, search_smoke, dossier_smoke)

    print("✅ Local sandbox refreshed. Data directory:", DATA_DIR)


local_app = typer.Typer(help="Bootstrap local sandbox data and verification smokes.")


def _exit_from_return(code: int | None) -> None:
    """Honor integer return codes from invoked helpers."""

    if isinstance(code, int) and code != 0:
        raise typer.Exit(code)


@local_app.command("reset", help="Wipe and reload local sandbox artifacts.")
def bootstrap_local_reset(
    skip_ocr: bool = typer.Option(False, "--skip-ocr", help="Skip generating chat screenshots and OCR."),
    skip_vector: bool = typer.Option(False, "--skip-vector", help="Skip rebuilding vector/structured stores."),
    bundle_uri: Optional[str] = typer.Option(
        None, "--bundle-uri", help="Optional bundle JSONL path/URI to place into data/bundles."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print planned actions without mutating disk."),
    report_dir: Path = typer.Option(REPORTS_DIR, "--report-dir", help="Verification report directory."),
    smoke_search: bool = typer.Option(False, "--smoke-search", help="Run Vertex search smoke after verification."),
    search_project: Optional[str] = typer.Option(
        None, "--search-project", help="Vertex project for search smoke (defaults to settings/env)."
    ),
    search_location: Optional[str] = typer.Option(
        None, "--search-location", help="Vertex location for search smoke (default from settings/env)."
    ),
    search_data_store_id: Optional[str] = typer.Option(
        None, "--search-data-store-id", help="Vertex data store id for search smoke."
    ),
    search_serving_config_id: str = typer.Option(
        "default_search", "--search-serving-config-id", help="Vertex serving config id for search smoke."
    ),
    search_query: str = typer.Option("wallet address verification", "--search-query", help="Search smoke query."),
    search_page_size: int = typer.Option(5, "--search-page-size", help="Search smoke page size."),
    smoke_dossiers: bool = typer.Option(False, "--smoke-dossiers", help="Run dossier verification smoke."),
    smoke_api_url: Optional[str] = typer.Option(
        None, "--smoke-api-url", help="API base URL for dossier smoke (defaults to env or localhost)."
    ),
    smoke_token: Optional[str] = typer.Option(None, "--smoke-token", help="API token for dossier smoke."),
    smoke_dossier_status: str = typer.Option(
        "completed", "--smoke-dossier-status", help="Queue status filter for dossier smoke."
    ),
    smoke_dossier_limit: int = typer.Option(5, "--smoke-dossier-limit", help="Maximum dossiers to inspect."),
    smoke_dossier_plan_id: Optional[str] = typer.Option(
        None, "--smoke-dossier-plan-id", help="Specific dossier plan_id to verify during smoke."
    ),
    force: bool = typer.Option(False, "--force", help="Allow running when I4G_ENV is not local."),
) -> None:
    """Reset local sandbox then reload sample data."""

    _exit_from_return(
        run_local(
            reset=True,
            skip_ocr=skip_ocr,
            skip_vector=skip_vector,
            bundle_uri=bundle_uri,
            dry_run=dry_run,
            verify_only=False,
            report_dir=report_dir,
            smoke_search=smoke_search,
            search_project=search_project,
            search_location=search_location,
            search_data_store_id=search_data_store_id,
            search_serving_config_id=search_serving_config_id,
            search_query=search_query,
            search_page_size=search_page_size,
            smoke_dossiers=smoke_dossiers,
            smoke_api_url=smoke_api_url,
            smoke_token=smoke_token,
            smoke_dossier_status=smoke_dossier_status,
            smoke_dossier_limit=smoke_dossier_limit,
            smoke_dossier_plan_id=smoke_dossier_plan_id,
            force=force,
        )
    )


@local_app.command("load", help="Refresh local sandbox without wiping artifacts.")
def bootstrap_local_load(
    skip_ocr: bool = typer.Option(False, "--skip-ocr", help="Skip generating chat screenshots and OCR."),
    skip_vector: bool = typer.Option(False, "--skip-vector", help="Skip rebuilding vector/structured stores."),
    bundle_uri: Optional[str] = typer.Option(
        None, "--bundle-uri", help="Optional bundle JSONL path/URI to place into data/bundles."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print planned actions without mutating disk."),
    report_dir: Path = typer.Option(REPORTS_DIR, "--report-dir", help="Verification report directory."),
    smoke_search: bool = typer.Option(False, "--smoke-search", help="Run Vertex search smoke after verification."),
    search_project: Optional[str] = typer.Option(
        None, "--search-project", help="Vertex project for search smoke (defaults to settings/env)."
    ),
    search_location: Optional[str] = typer.Option(
        None, "--search-location", help="Vertex location for search smoke (default from settings/env)."
    ),
    search_data_store_id: Optional[str] = typer.Option(
        None, "--search-data-store-id", help="Vertex data store id for search smoke."
    ),
    search_serving_config_id: str = typer.Option(
        "default_search", "--search-serving-config-id", help="Vertex serving config id for search smoke."
    ),
    search_query: str = typer.Option("wallet address verification", "--search-query", help="Search smoke query."),
    search_page_size: int = typer.Option(5, "--search-page-size", help="Search smoke page size."),
    smoke_dossiers: bool = typer.Option(False, "--smoke-dossiers", help="Run dossier verification smoke."),
    smoke_api_url: Optional[str] = typer.Option(
        None, "--smoke-api-url", help="API base URL for dossier smoke (defaults to env or localhost)."
    ),
    smoke_token: Optional[str] = typer.Option(None, "--smoke-token", help="API token for dossier smoke."),
    smoke_dossier_status: str = typer.Option(
        "completed", "--smoke-dossier-status", help="Queue status filter for dossier smoke."
    ),
    smoke_dossier_limit: int = typer.Option(5, "--smoke-dossier-limit", help="Maximum dossiers to inspect."),
    smoke_dossier_plan_id: Optional[str] = typer.Option(
        None, "--smoke-dossier-plan-id", help="Specific dossier plan_id to verify during smoke."
    ),
    force: bool = typer.Option(False, "--force", help="Allow running when I4G_ENV is not local."),
) -> None:
    """Refresh local sandbox data without a reset."""

    _exit_from_return(
        run_local(
            reset=False,
            skip_ocr=skip_ocr,
            skip_vector=skip_vector,
            bundle_uri=bundle_uri,
            dry_run=dry_run,
            verify_only=False,
            report_dir=report_dir,
            smoke_search=smoke_search,
            search_project=search_project,
            search_location=search_location,
            search_data_store_id=search_data_store_id,
            search_serving_config_id=search_serving_config_id,
            search_query=search_query,
            search_page_size=search_page_size,
            smoke_dossiers=smoke_dossiers,
            smoke_api_url=smoke_api_url,
            smoke_token=smoke_token,
            smoke_dossier_status=smoke_dossier_status,
            smoke_dossier_limit=smoke_dossier_limit,
            smoke_dossier_plan_id=smoke_dossier_plan_id,
            force=force,
        )
    )


@local_app.command("verify", help="Run verification only for the local sandbox.")
def bootstrap_local_verify(
    bundle_uri: Optional[str] = typer.Option(
        None, "--bundle-uri", help="Optional bundle JSONL path/URI to place into data/bundles."
    ),
    report_dir: Path = typer.Option(REPORTS_DIR, "--report-dir", help="Verification report directory."),
    smoke_search: bool = typer.Option(False, "--smoke-search", help="Run Vertex search smoke after verification."),
    search_project: Optional[str] = typer.Option(
        None, "--search-project", help="Vertex project for search smoke (defaults to settings/env)."
    ),
    search_location: Optional[str] = typer.Option(
        None, "--search-location", help="Vertex location for search smoke (default from settings/env)."
    ),
    search_data_store_id: Optional[str] = typer.Option(
        None, "--search-data-store-id", help="Vertex data store id for search smoke."
    ),
    search_serving_config_id: str = typer.Option(
        "default_search", "--search-serving-config-id", help="Vertex serving config id for search smoke."
    ),
    search_query: str = typer.Option("wallet address verification", "--search-query", help="Search smoke query."),
    search_page_size: int = typer.Option(5, "--search-page-size", help="Search smoke page size."),
    smoke_dossiers: bool = typer.Option(False, "--smoke-dossiers", help="Run dossier verification smoke."),
    smoke_api_url: Optional[str] = typer.Option(
        None, "--smoke-api-url", help="API base URL for dossier smoke (defaults to env or localhost)."
    ),
    smoke_token: Optional[str] = typer.Option(None, "--smoke-token", help="API token for dossier smoke."),
    smoke_dossier_status: str = typer.Option(
        "completed", "--smoke-dossier-status", help="Queue status filter for dossier smoke."
    ),
    smoke_dossier_limit: int = typer.Option(5, "--smoke-dossier-limit", help="Maximum dossiers to inspect."),
    smoke_dossier_plan_id: Optional[str] = typer.Option(
        None, "--smoke-dossier-plan-id", help="Specific dossier plan_id to verify during smoke."
    ),
    force: bool = typer.Option(False, "--force", help="Allow running when I4G_ENV is not local."),
) -> None:
    """Emit local verification reports without regenerating data."""

    _exit_from_return(
        run_local(
            reset=False,
            skip_ocr=False,
            skip_vector=False,
            bundle_uri=bundle_uri,
            dry_run=False,
            verify_only=True,
            report_dir=report_dir,
            smoke_search=smoke_search,
            search_project=search_project,
            search_location=search_location,
            search_data_store_id=search_data_store_id,
            search_serving_config_id=search_serving_config_id,
            search_query=search_query,
            search_page_size=search_page_size,
            smoke_dossiers=smoke_dossiers,
            smoke_api_url=smoke_api_url,
            smoke_token=smoke_token,
            smoke_dossier_status=smoke_dossier_status,
            smoke_dossier_limit=smoke_dossier_limit,
            smoke_dossier_plan_id=smoke_dossier_plan_id,
            force=force,
        )
    )


@local_app.command("smoke", help="Alias for local verification-only checks.")
def bootstrap_local_smoke(
    bundle_uri: Optional[str] = typer.Option(
        None, "--bundle-uri", help="Optional bundle JSONL path/URI to place into data/bundles."
    ),
    report_dir: Path = typer.Option(REPORTS_DIR, "--report-dir", help="Verification report directory."),
    smoke_search: bool = typer.Option(False, "--smoke-search", help="Run Vertex search smoke after verification."),
    smoke_dossiers: bool = typer.Option(False, "--smoke-dossiers", help="Run dossier verification smoke."),
    smoke_api_url: Optional[str] = typer.Option(
        None, "--smoke-api-url", help="API base URL for dossier smoke (defaults to env or localhost)."
    ),
    smoke_token: Optional[str] = typer.Option(None, "--smoke-token", help="API token for dossier smoke."),
    smoke_dossier_status: str = typer.Option(
        "completed", "--smoke-dossier-status", help="Queue status filter for dossier smoke."
    ),
    smoke_dossier_limit: int = typer.Option(5, "--smoke-dossier-limit", help="Maximum dossiers to inspect."),
    smoke_dossier_plan_id: Optional[str] = typer.Option(
        None, "--smoke-dossier-plan-id", help="Specific dossier plan_id to verify during smoke."
    ),
    force: bool = typer.Option(False, "--force", help="Allow running when I4G_ENV is not local."),
) -> None:
    """Run local verification-only checks (smoke alias)."""

    _exit_from_return(
        run_local(
            reset=False,
            skip_ocr=False,
            skip_vector=False,
            bundle_uri=bundle_uri,
            dry_run=False,
            verify_only=True,
            report_dir=report_dir,
            smoke_search=smoke_search,
            search_project=None,
            search_location=None,
            search_data_store_id=None,
            search_serving_config_id="default_search",
            search_query="wallet address verification",
            search_page_size=5,
            smoke_dossiers=smoke_dossiers,
            smoke_api_url=smoke_api_url,
            smoke_token=smoke_token,
            smoke_dossier_status=smoke_dossier_status,
            smoke_dossier_limit=smoke_dossier_limit,
            smoke_dossier_plan_id=smoke_dossier_plan_id,
            force=force,
        )
    )


__all__ = ["run_local", "local_app"]
