"""Individual bootstrap steps for the local sandbox."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

from .constants import (
    BUNDLES_DIR,
    CHAT_SCREENS_DIR,
    CHROMA_DIR,
    MANUAL_DEMO_DIR,
    OCR_OUTPUT,
    PILOT_CASES_PATH,
    REPORTS_DIR,
    ROOT,
    SEMANTIC_OUTPUT,
    SRC_DIR,
    SQLITE_DB,
    DEFAULT_PILOT_CASES,
)


def run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env_overrides: dict[str, str] | None = None,
    unset_env_vars: list[str] | None = None,
) -> None:
    """Execute a command, streaming stdout/stderr with PYTHONPATH set."""

    print("→", " ".join(cmd))
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    if unset_env_vars:
        for key in unset_env_vars:
            env.pop(key, None)

    existing_pythonpath = env.get("PYTHONPATH")
    pythonpath_parts = [str(SRC_DIR)]
    if existing_pythonpath:
        pythonpath_parts.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
    import subprocess

    subprocess.run(cmd, cwd=cwd or ROOT, check=True, env=env)


def reset_artifacts(skip_vector: bool) -> None:
    """Remove generated artifacts so the sandbox refreshes cleanly."""

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
    """Build scam bundles from adhoc scripts."""

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


def ingest_bundles(skip_vector: bool, limit: Optional[int] = None) -> None:
    """Ingest JSONL bundles into the local SQLite store."""

    bundles = sorted(BUNDLES_DIR.glob("**/*.jsonl"))

    if not bundles:
        print("⚠️  No bundles found to ingest.")
        return

    print(f"🚀 Ingesting {len(bundles)} bundles...")
    for bundle in bundles:
        print(f"   → Processing {bundle.name}...")
        env = {
            "I4G_INGEST__JSONL_PATH": str(bundle),
            "I4G_INGEST__ENABLE_VECTOR": "false" if skip_vector else "true",
            "I4G_INGEST__SKIP_CLASSIFICATION": "true",
            "I4G_STORAGE__STRUCTURED_BACKEND": "sqlite",
            "I4G_STORAGE__SQLITE_PATH": str(SQLITE_DB),
            "I4G_INGEST__MAX_RETRIES": "0",
        }
        if limit is not None:
            env["I4G_INGEST__BATCH_LIMIT"] = str(limit)
        run([sys.executable, "-m", "i4g.worker.jobs.ingest"], env_overrides=env, unset_env_vars=["I4G_DATABASE_URL"])


def stage_ocr_images() -> None:
    """Copy downloaded OCR test images to the processing directory."""

    source_dir = BUNDLES_DIR / "ocr_test_images"
    if not source_dir.exists():
        print(f"⚠️  OCR images bundle not found at {source_dir}. Skipping OCR staging.")
        return

    print(f"📸 Staging OCR images from {source_dir}...")
    CHAT_SCREENS_DIR.mkdir(parents=True, exist_ok=True)

    count = 0
    for item in source_dir.iterdir():
        if item.is_file():
            shutil.copy2(item, CHAT_SCREENS_DIR / item.name)
            count += 1
    print(f"   → Staged {count} images.")


def run_ocr() -> None:
    """Run OCR extraction on staged images."""

    from i4g.cli.extract import tasks as extract_tasks

    exit_code = extract_tasks.ocr(input_path=CHAT_SCREENS_DIR, output_path=OCR_OUTPUT)
    if exit_code:
        raise RuntimeError(f"OCR failed with exit code {exit_code}")


def run_semantic_extraction() -> None:
    """Run semantic extraction on OCR output."""

    from i4g.cli.extract import tasks as extract_tasks

    exit_code = extract_tasks.semantic(input_path=OCR_OUTPUT, output_path=SEMANTIC_OUTPUT, model="llama3.1")
    if exit_code:
        raise RuntimeError(f"Semantic extraction failed with exit code {exit_code}")


def rebuild_manual_demo() -> None:
    """Rebuild the manual ingestion demo (structured DB + vector store)."""

    run(
        [
            sys.executable,
            "tests/adhoc/manual_ingest_demo.py",
            "--structured-db",
            str(SQLITE_DB),
            "--vector-dir",
            str(CHROMA_DIR),
        ],
        env_overrides={
            "I4G_INGESTION__ENABLE_VERTEX": "false",
            "I4G_INGESTION__ENABLE_SQL": "true",
        },
        unset_env_vars=["I4G_DATABASE_URL"],
    )


def ensure_pilot_cases_file() -> None:
    """Seed the dossier pilot cases JSON if not already present."""

    if PILOT_CASES_PATH.exists():
        return
    PILOT_CASES_PATH.parent.mkdir(parents=True, exist_ok=True)
    PILOT_CASES_PATH.write_text(json.dumps(DEFAULT_PILOT_CASES, indent=2))
    print(f"🗂️  Seeded pilot cases config at {PILOT_CASES_PATH}")


def seed_review_cases() -> None:
    """Seed both synthetic and static review cases."""

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

    print("🌱 Seeding static review cases...")
    from i4g.cli.bootstrap.seed import seed_static_review_cases

    seed_static_review_cases()


def apply_migrations() -> None:
    """Apply Alembic migrations before seeding structured data."""

    run([sys.executable, "-m", "alembic", "upgrade", "head"], unset_env_vars=["I4G_DATABASE_URL"])


__all__ = [
    "run",
    "reset_artifacts",
    "ensure_dirs",
    "build_bundles",
    "ingest_bundles",
    "stage_ocr_images",
    "run_ocr",
    "run_semantic_extraction",
    "rebuild_manual_demo",
    "ensure_pilot_cases_file",
    "seed_review_cases",
    "apply_migrations",
]
