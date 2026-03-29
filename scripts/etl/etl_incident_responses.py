"""ETL script for Incident Report (Responses) Google Sheet → JSONL.

Usage:
    python scripts/etl/etl_incident_responses.py --csv data/bundles/incident_responses/raw.csv

The Google Sheet (https://docs.google.com/spreadsheets/d/1Aygqmpz_5LAwP7OZmm11AcZjIetvxJJ2xG6ms7_phvQ)
requires authenticated access.  Export the sheet manually as CSV and provide the path.

Output: data/bundles/incident_responses/cases.jsonl
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
import uuid
from pathlib import Path

# Minimum narrative length to accept a row (skip low-quality entries).
MIN_NARRATIVE_CHARS = 50

# Column mapping: expected CSV columns → internal field names.
# Adjust if the actual export headers differ.
_COLUMN_MAP = {
    "Timestamp": "timestamp",
    "Email Address": "reporter_email",
    "Date of Incident": "incident_date",
    "Type of Scam": "scam_type",
    "Description": "narrative",
    "URLs": "urls",
    "Email Addresses": "email_addresses",
    "Phone Numbers": "phone_numbers",
    "Wallet Addresses": "wallet_addresses",
    "Bank Accounts": "bank_accounts",
    "Loss Amount": "loss_amount",
    "Loss Currency": "loss_currency",
    "Victim Country": "victim_country",
    "Suspect Info": "suspect_info",
}


def _normalize_header(header: str) -> str:
    """Best-effort map from actual header to our internal name."""
    stripped = header.strip()
    if stripped in _COLUMN_MAP:
        return _COLUMN_MAP[stripped]
    # Fuzzy match: lowercase + strip
    lower = stripped.lower()
    for key, val in _COLUMN_MAP.items():
        if key.lower() in lower or lower in key.lower():
            return val
    return stripped.lower().replace(" ", "_")


def _extract_entities(row: dict) -> list[dict]:
    """Pull out structured entities from free-text indicator columns."""
    entities: list[dict] = []

    for raw in _split_multi(row.get("urls", "")):
        entities.append({"entity_type": "url", "canonical_value": raw, "confidence": 0.8})

    for raw in _split_multi(row.get("email_addresses", "")):
        entities.append({"entity_type": "email_address", "canonical_value": raw.lower(), "confidence": 0.85})

    for raw in _split_multi(row.get("phone_numbers", "")):
        entities.append({"entity_type": "phone_number", "canonical_value": raw, "confidence": 0.8})

    for raw in _split_multi(row.get("wallet_addresses", "")):
        entities.append({"entity_type": "wallet_address", "canonical_value": raw, "confidence": 0.85})

    for raw in _split_multi(row.get("bank_accounts", "")):
        entities.append({"entity_type": "bank_account", "canonical_value": raw, "confidence": 0.75})

    return entities


def _split_multi(value: str) -> list[str]:
    """Split a comma/newline delimited field into individual values."""
    if not value:
        return []
    parts = value.replace("\n", ",").split(",")
    return [p.strip() for p in parts if p.strip()]


def _parse_loss(raw: str) -> float | None:
    """Best-effort parse of a loss amount string."""
    if not raw:
        return None
    cleaned = raw.strip().replace("$", "").replace(",", "").replace(" ", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def convert(csv_path: Path, output_path: Path) -> int:
    """Read CSV, validate, and write JSONL.  Returns the number of cases written."""

    output_path.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped = 0

    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            print("ERROR: CSV appears empty or has no header row.")
            return 0

        # Build normalised header mapping
        rename = {orig: _normalize_header(orig) for orig in reader.fieldnames}

        with open(output_path, "w", encoding="utf-8") as out:
            for raw_row in reader:
                row = {rename.get(k, k): v for k, v in raw_row.items()}

                narrative = (row.get("narrative") or "").strip()
                if len(narrative) < MIN_NARRATIVE_CHARS:
                    skipped += 1
                    continue

                case_id = str(uuid.uuid5(uuid.NAMESPACE_URL, narrative))
                text_hash = hashlib.sha256(narrative.encode()).hexdigest()
                entities = _extract_entities(row)

                record = {
                    "case_id": case_id,
                    "dataset": "incident_responses",
                    "source_type": "form",
                    "text": narrative,
                    "raw_text_sha256": text_hash,
                    "classification": row.get("scam_type", "Unspecified"),
                    "classification_status": "pending",
                    "confidence": 0.0,
                    "entities": entities,
                    "metadata": {
                        "victim_country": row.get("victim_country", ""),
                        "loss_amount": _parse_loss(row.get("loss_amount", "")),
                        "loss_currency": row.get("loss_currency", "USD"),
                        "incident_date": row.get("incident_date", ""),
                        "suspect_info": row.get("suspect_info", ""),
                    },
                }

                out.write(json.dumps(record, default=str) + "\n")
                written += 1

    print(f"✅ Wrote {written} cases to {output_path} (skipped {skipped} low-quality rows).")
    return written


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Convert Incident Report Responses CSV → JSONL")
    parser.add_argument("--csv", required=True, type=Path, help="Path to the exported CSV file")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/bundles/incident_responses/cases.jsonl"),
        help="Output JSONL path",
    )
    args = parser.parse_args()

    if not args.csv.exists():
        print(f"ERROR: CSV not found at {args.csv}")
        sys.exit(1)

    count = convert(args.csv, args.output)
    if count == 0:
        print("WARNING: No cases produced. Check the CSV format and column mapping.")
        sys.exit(1)


if __name__ == "__main__":
    main()
