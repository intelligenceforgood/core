"""Build the consolidated golden data bundle from all sources.

Combines:
  1. Cleaned legacy Azure cases (legacy_azure_clean/cases.jsonl)
  2. Incident report responses (incident_responses/cases.jsonl)
  3. Golden seed SQL (golden_seed/seed.sql)

Output structure:
  data/bundles/golden/
    cases.jsonl    — consolidated case data for ingestion pipeline
    seed.sql       — direct DB inserts for campaigns, watchlists, graph, timeline
    manifest.json  — provenance info, counts, hashes, version

Usage:
    python scripts/build_golden_bundle.py [--bundles-dir data/bundles] [--output-dir data/bundles/golden]
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

MIN_TEXT_CHARS = 50

# Bundles to combine and their sub-paths (relative to bundles_dir)
_BUNDLE_SOURCES = [
    ("legacy_azure_clean", "legacy_azure_clean/cases.jsonl", False),
    ("incident_responses", "incident_responses/cases.jsonl", False),
]


def _collect_jsonl(path: Path) -> list[str]:
    """Read lines from a single .jsonl file or all .jsonl files in a dir."""
    lines: list[str] = []
    if path.is_file():
        with open(path, encoding="utf-8") as fh:
            lines.extend(fh.readlines())
    elif path.is_dir():
        for f in sorted(path.rglob("*.jsonl")):
            with open(f, encoding="utf-8") as fh:
                lines.extend(fh.readlines())
    return lines


def build(bundles_dir: Path, output_dir: Path, skip_ids: set[str] | None = None) -> dict:
    """Build the golden bundle and return a manifest dict."""

    output_dir.mkdir(parents=True, exist_ok=True)
    skip_ids = skip_ids or set()

    seen_hashes: set[str] = set()
    total_written = 0
    source_counts: dict[str, int] = {}

    out_jsonl = output_dir / "cases.jsonl"

    with open(out_jsonl, "w", encoding="utf-8") as out:
        for source_name, rel_path, _is_dir_source in _BUNDLE_SOURCES:
            source_path = bundles_dir / rel_path
            if not source_path.exists():
                print(f"⚠️  Source {source_name} not found at {source_path}. Skipping.")
                source_counts[source_name] = 0
                continue

            lines = _collect_jsonl(source_path)
            count = 0

            for line in lines:
                line = line.strip()
                if not line:
                    continue

                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Skip by case_id (some sources use "id", others use "case_id")
                case_id = record.get("case_id") or record.get("id") or ""
                if case_id in skip_ids:
                    continue

                # Skip short text
                text = record.get("text", "") or ""
                if len(text) < MIN_TEXT_CHARS:
                    continue

                # Dedup by content hash
                text_hash = record.get("raw_text_sha256") or hashlib.sha256(text.encode()).hexdigest()
                if text_hash in seen_hashes:
                    continue
                seen_hashes.add(text_hash)

                out.write(json.dumps(record, default=str) + "\n")
                count += 1
                total_written += 1

            source_counts[source_name] = count
            print(f"  📦 {source_name}: {count} cases")

    # Copy seed SQL
    seed_sql_src = bundles_dir / "golden_seed" / "seed.sql"
    seed_sql_dst = output_dir / "seed.sql"
    if seed_sql_src.exists():
        shutil.copy2(seed_sql_src, seed_sql_dst)
        print(f"  📝 Copied seed.sql ({seed_sql_src.stat().st_size} bytes)")
    else:
        print("  ⚠️  No seed.sql found; skipping.")

    # Compute file hash for manifest
    jsonl_hash = hashlib.sha256(out_jsonl.read_bytes()).hexdigest()

    manifest = {
        "version": "1.0",
        "created_at": datetime.now(UTC).isoformat(),
        "total_cases": total_written,
        "source_counts": source_counts,
        "jsonl_sha256": jsonl_hash,
        "min_text_chars": MIN_TEXT_CHARS,
        "skip_ids": sorted(skip_ids),
    }

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\n✅ Golden bundle built: {total_written} cases → {output_dir}")
    print(f"   Manifest: {manifest_path}")

    return manifest


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Build consolidated golden data bundle")
    parser.add_argument("--bundles-dir", type=Path, default=Path("data/bundles"), help="Root bundles directory")
    parser.add_argument("--output-dir", type=Path, default=Path("data/bundles/golden"), help="Output directory")
    parser.add_argument(
        "--skip-ids", type=Path, default=None, help="Path to text file with case IDs to skip (one per line)"
    )
    args = parser.parse_args()

    skip_ids: set[str] = set()
    if args.skip_ids and args.skip_ids.exists():
        skip_ids = {line.strip() for line in args.skip_ids.read_text().splitlines() if line.strip()}
        print(f"Loaded {len(skip_ids)} case IDs to skip.")

    build(args.bundles_dir, args.output_dir, skip_ids)


if __name__ == "__main__":
    main()
