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
import re
import sys
import uuid
from pathlib import Path

# Minimum narrative length to accept a row (skip low-quality entries).
MIN_NARRATIVE_CHARS = 50

# Column mapping: expected CSV columns → internal field names.
# These match the actual Google Sheet "Incident Report (Responses)" export.
_COLUMN_MAP = {
    "Timestamp": "timestamp",
    "Email Address": "reporter_email",
    "First Name": "first_name",
    "Last Name": "last_name",
    "Country": "victim_country",
    "City": "victim_city",
    "State / Province": "victim_state",
    "Have you reported this incident to Law Enforcement?": "reported_to_law",
    "If yes, what law enforcement agency(ies)?": "law_agencies",
    "Tell us what happened, including how the criminal first contacted you.": "narrative",
    "When you were asked to send money, how did you send it?": "payment_method",
    "If you wired money, please provide the bank account information"
    " the criminal provided to you below:": "bank_accounts",
    "If cryptocurrency, please provide the type of crypto as well as the"
    " sending and receiving wallet addresses:": "wallet_addresses",
    "Please provide the name of any mobile apps you were asked to use or" " the URL of the investment website:": "urls",
    "Please provide the phone number(s), email address(es), WhatsApp or"
    " Telegram handles of the criminals who communicated with you:": "contact_handles",
    "If the criminals provided a street address/mailing address at any"
    " point, please share that here:": "suspect_address",
    "If CashApp, PayPal, Venmo, etc., please provide all user names /" " handles / tags here:  ": "payment_handles",
    "Please share any additional information you feel would be helpful in"
    " understanding and investigating your case.": "additional_info",
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
    """Pull out structured entities from free-text indicator columns.

    Each column gets purpose-built extraction — regex patterns matched to the
    actual data observed in the incident-response spreadsheet.  No naive
    split-and-hope.
    """
    entities: list[dict] = []

    # --- URLs -----------------------------------------------------------------
    for raw in _split_multi(row.get("urls", "")):
        if _looks_like_url(raw):
            entities.append({"entity_type": "url", "canonical_value": raw.strip(), "confidence": 0.8})

    # --- Contact handles → emails, phones, social handles --------------------
    _extract_contact_handles(row.get("contact_handles", ""), entities)

    # --- Wallet addresses (regex extraction — already battle-tested) ----------
    wallet_text = row.get("wallet_addresses", "")
    for addr in _extract_wallet_addresses(wallet_text):
        entities.append({"entity_type": "wallet_address", "canonical_value": addr, "confidence": 0.85})

    # --- Bank accounts → account numbers, routing numbers, IBANs -------------
    _extract_bank_accounts(row.get("bank_accounts", ""), entities)

    # --- Payment handles → CashApp $tags, emails, @handles ------------------
    _extract_payment_handles(row.get("payment_handles", ""), entities)

    return entities


# ---------------------------------------------------------------------------
# Per-column extraction helpers
# ---------------------------------------------------------------------------

# Phone number patterns (international and US domestic)
_PHONE_RE = re.compile(
    r"""
    (?:\+\d{1,3}[\s.-]?)?       # optional country code
    (?:\(?\d{3}\)?[\s.\-]?)?     # optional area code
    \d{3}[\s.\-]?\d{4}           # 7-digit local number
    """,
    re.VERBOSE,
)
# Stricter: must have at least 7 digits total once non-digits are removed
_MIN_PHONE_DIGITS = 7

_EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}")
_TELEGRAM_HANDLE_RE = re.compile(r"@[A-Za-z]\w{2,}")
_TELEGRAM_LINK_RE = re.compile(r"t\.me/([A-Za-z]\w{2,})")


def _extract_contact_handles(text: str, entities: list[dict]) -> None:
    """Extract emails, phone numbers, and social handles from contact_handles column."""
    if not text:
        return

    seen: set[str] = set()

    # Emails
    for m in _EMAIL_RE.finditer(text):
        val = m.group().lower().strip().rstrip(".")
        if val not in seen:
            seen.add(val)
            entities.append({"entity_type": "email_address", "canonical_value": val, "confidence": 0.9})

    # t.me/ links → social handles
    for m in _TELEGRAM_LINK_RE.finditer(text):
        handle = "@" + m.group(1)
        key = handle.lower()
        if key not in seen:
            seen.add(key)
            entities.append({"entity_type": "social_handle", "canonical_value": handle, "confidence": 0.85})

    # @handles (Telegram / social)
    for m in _TELEGRAM_HANDLE_RE.finditer(text):
        handle = m.group()
        key = handle.lower()
        if key not in seen:
            seen.add(key)
            entities.append({"entity_type": "social_handle", "canonical_value": handle, "confidence": 0.85})

    # Phone numbers
    for m in _PHONE_RE.finditer(text):
        raw_phone = m.group()
        digits = re.sub(r"\D", "", raw_phone)
        if len(digits) < _MIN_PHONE_DIGITS:
            continue
        # Skip if this looks like it's part of an already-extracted email
        start = max(0, m.start() - 1)
        surrounding = text[start : m.end() + 1]
        if "@" in surrounding:
            continue
        canonical = "+" + digits if raw_phone.strip().startswith("+") else digits
        if canonical not in seen:
            seen.add(canonical)
            entities.append({"entity_type": "phone_number", "canonical_value": canonical, "confidence": 0.85})


# Bank account extraction patterns
_ACCOUNT_NUM_RE = re.compile(r"(?:Account\s*(?:Number|#|No\.?)\s*:?\s*)(\d[\d\s\-]{4,19}\d)", re.IGNORECASE)
_ROUTING_NUM_RE = re.compile(r"(?:Routing\s*(?:Number|#|No\.?)\s*:?\s*)(\d{9})", re.IGNORECASE)
_IBAN_RE = re.compile(r"\b([A-Z]{2}\d{2}\s?\d{4}\s?\d{4}\s?\d{4}\s?[\d\s]{0,14})\b")
_SWIFT_RE = re.compile(
    r"(?:SWIFT|BIC|SWIFT/BIC)\s*(?:Code|#|No\.?)?\s*[:：]?\s*([A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?)\b",
    re.IGNORECASE,
)
_BSB_RE = re.compile(r"(?:BSB\s*(?:Number)?\s*:?\s*)(\d{3}[\s-]?\d{3})", re.IGNORECASE)
_BARE_ACCT_RE = re.compile(r"(?:Account|Acct)[\s#:]*(\d{6,20})", re.IGNORECASE)


def _extract_bank_accounts(text: str, entities: list[dict]) -> None:
    """Extract account numbers, routing numbers, and IBANs from bank_accounts column."""
    if not text:
        return

    seen: set[str] = set()

    # Routing numbers (US ABA — exactly 9 digits)
    for m in _ROUTING_NUM_RE.finditer(text):
        val = m.group(1).strip()
        if val not in seen:
            seen.add(val)
            entities.append({"entity_type": "bank_account", "canonical_value": val, "confidence": 0.9})

    # Account numbers (labeled)
    for pattern in (_ACCOUNT_NUM_RE, _BARE_ACCT_RE):
        for m in pattern.finditer(text):
            val = re.sub(r"[\s\-]", "", m.group(1))
            if val not in seen and len(val) >= 6:
                seen.add(val)
                entities.append({"entity_type": "bank_account", "canonical_value": val, "confidence": 0.9})

    # IBAN
    for m in _IBAN_RE.finditer(text):
        val = re.sub(r"\s", "", m.group(1))
        if len(val) >= 15 and val not in seen:
            seen.add(val)
            entities.append({"entity_type": "bank_account", "canonical_value": val, "confidence": 0.9})

    # SWIFT/BIC codes (only when labeled as SWIFT/BIC to avoid false positives)
    for m in _SWIFT_RE.finditer(text):
        val = m.group(1).upper()
        if val not in seen and len(val) >= 8:
            seen.add(val)
            entities.append({"entity_type": "bank_account", "canonical_value": val, "confidence": 0.8})

    # BSB numbers (Australian)
    for m in _BSB_RE.finditer(text):
        val = re.sub(r"\s", "", m.group(1))
        if val not in seen:
            seen.add(val)
            entities.append({"entity_type": "bank_account", "canonical_value": val, "confidence": 0.85})


# Payment handle extraction patterns
_CASHAPP_RE = re.compile(r"\$([A-Za-z]\w{2,})")
_VENMO_PAYPAL_HANDLE_RE = re.compile(r"@([A-Za-z]\w{2,})")


def _extract_payment_handles(text: str, entities: list[dict]) -> None:
    """Extract CashApp $tags, emails, @handles, and wallet addresses from payment_handles column."""
    if not text:
        return

    seen: set[str] = set()

    # CashApp $tags
    for m in _CASHAPP_RE.finditer(text):
        tag = "$" + m.group(1)
        key = tag.lower()
        if key not in seen and not _is_junk_value(m.group(1)):
            seen.add(key)
            entities.append({"entity_type": "payment_handle", "canonical_value": tag, "confidence": 0.9})

    # Emails (Zelle, PayPal, Venmo accounts often use email)
    for m in _EMAIL_RE.finditer(text):
        val = m.group().lower().strip().rstrip(".")
        if val not in seen:
            seen.add(val)
            entities.append({"entity_type": "email_address", "canonical_value": val, "confidence": 0.85})

    # @handles (Venmo, PayPal)
    for m in _VENMO_PAYPAL_HANDLE_RE.finditer(text):
        handle = "@" + m.group(1)
        key = handle.lower()
        # Skip if it's part of an email already captured
        start = m.start()
        if start > 0 and text[start - 1] not in (" ", "\n", "\t", ",", ";"):
            continue
        if key not in seen:
            seen.add(key)
            entities.append({"entity_type": "payment_handle", "canonical_value": handle, "confidence": 0.8})

    # Wallet addresses that end up in the payment_handles column
    for addr in _extract_wallet_addresses(text):
        if addr not in seen:
            seen.add(addr)
            entities.append({"entity_type": "wallet_address", "canonical_value": addr, "confidence": 0.85})

    # Phone numbers (Zelle uses phone numbers)
    for m in _PHONE_RE.finditer(text):
        raw_phone = m.group()
        digits = re.sub(r"\D", "", raw_phone)
        if len(digits) < _MIN_PHONE_DIGITS:
            continue
        start = max(0, m.start() - 1)
        surrounding = text[start : m.end() + 1]
        if "@" in surrounding:
            continue
        canonical = "+" + digits if raw_phone.strip().startswith("+") else digits
        if canonical not in seen:
            seen.add(canonical)
            entities.append({"entity_type": "phone_number", "canonical_value": canonical, "confidence": 0.8})


# Wallet address patterns (match actual crypto addresses, not dollar amounts or keywords)
_ETH_RE = re.compile(r"\b0x[0-9a-fA-F]{40}\b")
_BTC_BECH32_RE = re.compile(r"\bbc1[a-zA-HJ-NP-Z0-9]{25,87}\b")
_BTC_LEGACY_RE = re.compile(r"\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b")
_SOL_RE = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b")  # Base58, 32-44 chars


def _extract_wallet_addresses(text: str) -> list[str]:
    """Extract real crypto wallet addresses from free-text using regex."""
    if not text:
        return []
    addresses: set[str] = set()
    addresses.update(_ETH_RE.findall(text))
    addresses.update(_BTC_BECH32_RE.findall(text))
    addresses.update(_BTC_LEGACY_RE.findall(text))
    # For Solana-style base58 addresses, only match if they look long enough
    for m in _SOL_RE.findall(text):
        if len(m) >= 32 and not _is_junk_value(m):
            addresses.update([m])
    return sorted(addresses)


# Junk values commonly found in free-text indicator columns
_JUNK_WORDS = frozenset(
    w.lower()
    for w in [
        "N/A",
        "NA",
        "n/a",
        "None",
        "none",
        "Bitcoin",
        "bitcoin",
        "BTC",
        "ETH",
        "Ethereum",
        "USDT",
        "Tether",
        "unknown",
        "Unknown",
        "no",
        "No",
        "yes",
        "Yes",
        "Hash",
    ]
)

_JUNK_RE = re.compile(
    r"^[\$\d\.,\s/\-]+$"  # Only dollar amounts, digits, dates, slashes
    r"|^\d{1,2}/\d{1,2}/\d{2,4}$"  # Date patterns
)


def _is_junk_value(val: str) -> bool:
    """Check if a value is a known junk/placeholder."""
    stripped = val.strip()
    if not stripped or len(stripped) < 3:
        return True
    if stripped.lower() in _JUNK_WORDS:
        return True
    return bool(_JUNK_RE.match(stripped))


def _looks_like_url(val: str) -> bool:
    """Check if a value looks like a URL or domain."""
    stripped = val.strip()
    if not stripped:
        return False
    if stripped.startswith(("http://", "https://", "www.")):
        return True
    return "." in stripped and " " not in stripped and len(stripped) > 4


def _split_multi(value: str) -> list[str]:
    """Split a comma/newline/semicolon delimited field into individual values."""
    if not value:
        return []
    parts = re.split(r"[,;\n]", value)
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
                    "classification": "Unspecified",
                    "classification_status": "pending",
                    "confidence": 0.0,
                    "entities": entities,
                    "metadata": {
                        "victim_country": row.get("victim_country", ""),
                        "victim_city": row.get("victim_city", ""),
                        "victim_state": row.get("victim_state", ""),
                        "payment_method": row.get("payment_method", ""),
                        "reported_to_law": row.get("reported_to_law", ""),
                        "law_agencies": row.get("law_agencies", ""),
                        "suspect_address": row.get("suspect_address", ""),
                        "additional_info": row.get("additional_info", ""),
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
