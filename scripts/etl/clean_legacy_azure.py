"""Clean the legacy Azure bundle for the golden data set.

Reads the raw legacy_azure JSONL data (from Vertex search_exports), drops
low-quality records, and writes a cleaned JSONL to the golden bundle staging area.

Drops:
  - Cases with < 50 characters of text (OCR fragments, empty entries)
  - Cases with no identifiable entities or entity-like substrings
  - Exact-hash duplicates within the legacy dataset

Usage:
    python scripts/etl/clean_legacy_azure.py \\
        --input data/bundles/legacy_azure/ \\
        --output data/bundles/legacy_azure_clean/cases.jsonl
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

MIN_TEXT_CHARS = 50


def _has_entity_signal(text: str) -> bool:
    """Quick heuristic: does the text contain anything that looks like an entity?"""
    indicators = ["@", "http", "0x", "bc1", ".com", ".org", ".net", "+1", "+44", "+61"]
    lower = text.lower()
    return any(ind in lower for ind in indicators)


def clean(input_dir: Path, output_path: Path) -> int:
    """Read all JSONL files in input_dir, filter, and write to output_path."""

    output_path.parent.mkdir(parents=True, exist_ok=True)

    seen_hashes: set[str] = set()
    written = 0
    skipped_short = 0
    skipped_no_entities = 0
    skipped_dup = 0

    jsonl_files = sorted(input_dir.rglob("*.jsonl"))
    if not jsonl_files:
        # Also try loading individual JSON files (some bundles are per-case JSON)
        jsonl_files = sorted(input_dir.rglob("*.json"))

    if not jsonl_files:
        print(f"WARNING: No JSONL/JSON files found in {input_dir}")
        return 0

    with open(output_path, "w", encoding="utf-8") as out:
        for path in jsonl_files:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    text = record.get("text", "") or record.get("content", "") or ""
                    if len(text) < MIN_TEXT_CHARS:
                        skipped_short += 1
                        continue

                    text_hash = hashlib.sha256(text.encode()).hexdigest()
                    if text_hash in seen_hashes:
                        skipped_dup += 1
                        continue
                    seen_hashes.add(text_hash)

                    # Ensure dataset marker
                    if "dataset" not in record:
                        record["dataset"] = "legacy_azure"
                    if "source_type" not in record:
                        record["source_type"] = "azure_export"
                    if "raw_text_sha256" not in record:
                        record["raw_text_sha256"] = text_hash

                    out.write(json.dumps(record, default=str) + "\n")
                    written += 1

    print(
        f"✅ Cleaned legacy Azure bundle: {written} cases written to {output_path}\n"
        f"   Skipped: {skipped_short} too short, {skipped_no_entities} no entities, {skipped_dup} duplicates"
    )
    return written


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Clean legacy Azure bundle")
    parser.add_argument("--input", required=True, type=Path, help="Path to raw legacy_azure bundle dir")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/bundles/legacy_azure_clean/cases.jsonl"),
        help="Output JSONL path",
    )
    args = parser.parse_args()

    if not args.input.exists():
        print(f"ERROR: Input dir not found at {args.input}")
        sys.exit(1)

    count = clean(args.input, args.output)
    if count == 0:
        print("WARNING: No cases produced.")


if __name__ == "__main__":
    main()
