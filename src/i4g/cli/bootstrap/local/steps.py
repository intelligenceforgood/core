"""Individual bootstrap steps for the local sandbox."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from .constants import (
    BUNDLES_DIR,
    CHAT_SCREENS_DIR,
    CHROMA_DIR,
    DEFAULT_PILOT_CASES,
    MANUAL_DEMO_DIR,
    OCR_OUTPUT,
    PILOT_CASES_PATH,
    REPORTS_DIR,
    ROOT,
    SEMANTIC_OUTPUT,
    SQLITE_DB,
    SRC_DIR,
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
    # Always remove SQLite (including WAL/SHM) so reset starts clean.
    for suffix in ("", "-wal", "-shm"):
        p = SQLITE_DB.parent / (SQLITE_DB.name + suffix)
        if p.exists():
            p.unlink()
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


def _is_golden_mode() -> bool:
    """Return True when the golden bundle is available locally."""
    golden_path = BUNDLES_DIR / "golden" / "cases.jsonl"
    return golden_path.exists()


def ingest_golden_fast(*, skip_extraction: bool = False) -> bool:
    """Fast-path: insert golden JSONL directly into SQLite.

    Bypasses the heavyweight IngestPipeline (StructuredStore + SqlWriter +
    VectorStore) by doing raw sqlite3 inserts.  Populates the same tables the
    pipeline would: ``cases``, ``source_documents``, ``entities``, and
    ``scam_records``.

    Args:
        skip_extraction: If True, use pre-labeled entities from the JSONL
            (original behavior). If False, run the extraction orchestrator
            on each case's text and store the resulting entities.

    Returns True on success, False if the golden bundle is missing.
    """
    import hashlib
    import sqlite3
    import uuid
    from datetime import UTC, datetime

    golden_path = BUNDLES_DIR / "golden" / "cases.jsonl"
    if not golden_path.exists():
        print("⚠️  Golden bundle not found at", golden_path)
        return False

    print("🚀 Fast-ingesting golden bundle into SQLite...")
    conn = sqlite3.connect(str(SQLITE_DB))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    cur = conn.cursor()
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")

    # Use bundle build date as first_seen_at so KPI "new indicators" doesn't
    # count historical data as new after a bootstrap.
    manifest_path = golden_path.parent / "manifest.json"
    bundle_date = now  # fallback
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            raw_ts = manifest.get("created_at", "")
            if raw_ts:
                bundle_date = datetime.fromisoformat(raw_ts).strftime("%Y-%m-%d %H:%M:%S")
        except (json.JSONDecodeError, ValueError, KeyError):
            pass  # keep fallback

    count = 0
    entity_count = 0
    indicator_count = 0
    with open(golden_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)

            case_id = record.get("id") or record.get("case_id") or str(uuid.uuid4())
            struct_data = record.get("structData") or {}
            text = record.get("text", "") or struct_data.get("content", "")
            dataset = record.get("dataset", "golden")
            source_type = record.get("source_type", "golden_bundle")
            classification = record.get("classification", "unclassified")
            raw_hash = record.get("raw_text_sha256") or hashlib.sha256(text.encode()).hexdigest()
            metadata = record.get("metadata") or {}
            if not isinstance(metadata, dict):
                metadata = {}
            title = struct_data.get("title", "")
            if title:
                metadata["title"] = title
            # Normalize entities: ETL scripts produce [{entity_type, canonical_value, confidence}]
            # but the old code expected {type: [values]}.  Convert list→dict for storage.
            if skip_extraction:
                raw_entities = record.get("entities")
                entities_dict: dict[str, list[str]] = {}
                if isinstance(raw_entities, list):
                    for ent in raw_entities:
                        if not isinstance(ent, dict):
                            continue
                        etype = ent.get("entity_type", "unknown")
                        val = ent.get("canonical_value", "")
                        if val:
                            entities_dict.setdefault(etype, []).append(val)
                elif isinstance(raw_entities, dict):
                    entities_dict = raw_entities
            else:
                # Run orchestrator on the case text for real extraction.
                from i4g.extraction.orchestrator import extract_entities

                result = extract_entities(text, modules=["regex", "heuristic"])
                entities_dict = {}
                for scored in result.entities:
                    entities_dict.setdefault(scored.entity_type, []).append(scored.canonical_value)

            # -- cases table --
            cur.execute(
                "INSERT INTO cases "
                "(case_id, dataset, source_type, classification, classification_status, "
                "raw_text_sha256, description, status, metadata, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(case_id) DO NOTHING",
                (
                    case_id,
                    dataset,
                    source_type,
                    classification,
                    "pending",
                    raw_hash,
                    text,
                    "open",
                    json.dumps(metadata),
                    now,
                    now,
                ),
            )

            # -- scam_records table (primary table the UI reads) --
            cur.execute(
                "INSERT INTO scam_records "
                "(case_id, text, entities, classification, confidence, metadata, created_at) "
                "VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(case_id) DO UPDATE SET text=excluded.text, entities=excluded.entities",
                (case_id, text, json.dumps(entities_dict), classification, 0.0, json.dumps(metadata), now),
            )

            # -- source_documents table --
            doc_id = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO source_documents "
                "(document_id, case_id, title, text, text_sha256, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT DO NOTHING",
                (doc_id, case_id, title, text, raw_hash, now, now),
            )

            # -- entities table --
            from i4g.utils.entity_types import normalize_entity_type

            for raw_etype, values in entities_dict.items():
                if not isinstance(values, list):
                    continue
                etype = normalize_entity_type(raw_etype)
                for val in values:
                    canonical = val if isinstance(val, str) else (val.get("value") or str(val))
                    if not canonical:
                        continue
                    eid = str(uuid.uuid4())
                    cur.execute(
                        "INSERT INTO entities "
                        "(entity_id, case_id, entity_type, canonical_value, raw_value, "
                        "confidence, first_seen_at, last_seen_at, created_at, updated_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?) "
                        "ON CONFLICT DO NOTHING",
                        (eid, case_id, etype, canonical, canonical, 0.0, bundle_date, bundle_date, now, now),
                    )
                    entity_count += 1

            # -- indicators table (IoC view of entities) --
            for raw_etype2, values in entities_dict.items():
                if not isinstance(values, list):
                    continue
                etype2 = normalize_entity_type(raw_etype2)
                for val in values:
                    canonical = val if isinstance(val, str) else (val.get("value") or str(val))
                    if not canonical:
                        continue
                    iid = str(uuid.uuid4())
                    cur.execute(
                        "INSERT INTO indicators "
                        "(indicator_id, case_id, category, type, number, dataset, "
                        "status, confidence, first_seen_at, last_seen_at, "
                        "created_at, updated_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
                        "ON CONFLICT DO NOTHING",
                        (
                            iid,
                            case_id,
                            etype2,
                            etype2,
                            canonical,
                            dataset,
                            "active",
                            0.0,
                            bundle_date,
                            bundle_date,
                            now,
                            now,
                        ),
                    )
                    indicator_count += 1

            count += 1

    conn.commit()
    conn.close()
    print(f"✅ Fast-ingested {count} cases, {entity_count} entities, {indicator_count} indicators into SQLite.")
    return True


def ingest_bundles(skip_vector: bool, limit: int | None = None, skip_extraction: bool = False) -> None:
    """Ingest JSONL bundles into the local SQLite store."""

    # Golden mode: use the fast direct-to-SQLite path
    if _is_golden_mode():
        if ingest_golden_fast(skip_extraction=skip_extraction):
            return
        print("⚠️  Golden fast-path failed; falling back to standard ingestion.")

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


def run_analytics_refresh() -> None:
    """Run analytics aggregation to populate entity_stats, indicator_stats, campaign_stats.

    This step is critical: intelligence pages (campaigns, indicators, graph)
    read from pre-computed stats tables.  Without this, those pages are empty.
    """

    print("📊 Running analytics aggregation...")
    try:
        from i4g.worker.jobs.analytics_aggregation import main as analytics_main

        result = analytics_main()
        if result != 0:
            print(f"⚠️  Analytics aggregation exited with code {result}. Intelligence pages may be incomplete.")
        else:
            print("   → Analytics aggregation complete.")
    except Exception as exc:
        print(f"⚠️  Analytics aggregation failed: {exc}. Intelligence pages may be incomplete.")


def apply_seed_sql() -> None:
    """Apply seed.sql from the golden bundle to the local SQLite store.

    The seed SQL references placeholder case IDs (``golden-case-XXXX``).  This
    function substitutes them with real case IDs already present in the
    ``cases`` table so that foreign-key relationships and UI joins work.
    """

    seed_path = BUNDLES_DIR / "golden" / "seed.sql"
    if not seed_path.exists():
        # Fall back to golden_seed location (pre-consolidation)
        seed_path = BUNDLES_DIR / "golden_seed" / "seed.sql"
    if not seed_path.exists():
        print("⚠️  No seed.sql found in golden bundle. Skipping.")
        return

    import re
    import sqlite3

    print(f"🌱 Applying seed SQL from {seed_path.name}...")
    sql = seed_path.read_text(encoding="utf-8")

    conn = sqlite3.connect(str(SQLITE_DB))
    try:
        # Gather real case IDs to replace golden-case-XXXX placeholders
        real_ids = [row[0] for row in conn.execute("SELECT case_id FROM cases ORDER BY case_id").fetchall()]

        placeholders = sorted(set(re.findall(r"golden-case-\d{4}", sql)))
        if placeholders and real_ids:
            for i, ph in enumerate(placeholders):
                real = real_ids[i % len(real_ids)]
                sql = sql.replace(ph, real)
            print(f"   → Replaced {len(placeholders)} placeholder IDs with real case IDs.")
        elif placeholders:
            print(
                f"   ❌ No real case IDs in DB; cannot resolve {len(placeholders)} "
                "placeholder IDs. Run ingestion first, then re-run seed SQL."
            )
            return

        conn.executescript(sql)
        conn.commit()
        print("   → Seed SQL applied successfully.")
    finally:
        conn.close()


__all__ = [
    "run",
    "reset_artifacts",
    "ensure_dirs",
    "build_bundles",
    "ingest_bundles",
    "ingest_golden_fast",
    "stage_ocr_images",
    "run_ocr",
    "run_semantic_extraction",
    "rebuild_manual_demo",
    "ensure_pilot_cases_file",
    "seed_review_cases",
    "apply_migrations",
    "run_analytics_refresh",
    "apply_seed_sql",
]
