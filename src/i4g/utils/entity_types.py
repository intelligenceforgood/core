"""Entity type canonical definitions — the single source of truth.

Every entity that enters the database MUST use a canonical type defined here.
All write paths (LLM extraction, rule-based extraction, golden-bundle ingest,
SqlWriter, ETL scripts) call ``normalize_entity_type()`` before persisting.
Read paths should NEVER need translation — entity_type values in the DB are
already canonical.
"""

from __future__ import annotations

import re
from collections.abc import Callable

# ---------------------------------------------------------------------------
# Canonical entity types and their display labels
# ---------------------------------------------------------------------------

ENTITY_TYPE_LABELS: dict[str, str] = {
    "person": "Person",
    "organization": "Organization",
    "phone_number": "Phone Number",
    "wallet_address": "Wallet Address",
    "transaction_id": "Transaction ID",
    "ticket_id": "Ticket ID",
    "location": "Location",
    "bank_account": "Bank Account",
    "agency": "Agency",
    "social_handle": "Social Handle",
    "crypto_token": "Crypto Token",
    "scam_indicator": "Scam Indicator",
    "email_address": "Email Address",
    "url": "URL",
    "domain": "Domain",
    "ip_address": "IP Address",
    "payment_handle": "Payment Handle",
    "contact_handle": "Contact Handle",
}

# The set of valid canonical types (derived from the labels dict above).
CANONICAL_ENTITY_TYPES: frozenset[str] = frozenset(ENTITY_TYPE_LABELS)

# Entity types that represent actionable threat infrastructure — financial
# accounts, digital identifiers, and contact mechanisms.  Used by the
# dashboard "Active Threats" widget to filter out contextual NER noise
# (person names, organizations, locations) that inflate the count after
# LLM entity extraction.
THREAT_ENTITY_TYPES: frozenset[str] = frozenset(
    {
        "wallet_address",
        "bank_account",
        "payment_handle",
        "email_address",
        "phone_number",
        "social_handle",
        "contact_handle",
        "crypto_token",
        "url",
        "domain",
        "ip_address",
        "transaction_id",
    }
)

# ---------------------------------------------------------------------------
# Normalization map — maps every known variant to its canonical form.
# Only used at write time so the DB is always clean.
# ---------------------------------------------------------------------------

_ENTITY_TYPE_MAP: dict[str, str] = {
    # LLM extraction keys (plural / category-style)
    "people": "person",
    "organizations": "organization",
    "wallet_addresses": "wallet_address",
    "crypto_assets": "crypto_token",
    "contact_channels": "contact_handle",
    "locations": "location",
    "scam_indicators": "scam_indicator",
    # Rule-based / ML NER extraction keys
    "urls": "url",
    "phone_numbers": "phone_number",
    "email_addresses": "email_address",
    "email_address": "email_address",
    "emails": "email_address",
    "bank_accounts": "bank_account",
    "bank_account": "bank_account",
    "account_numbers": "bank_account",
    "account_number": "bank_account",
    "routing_numbers": "bank_account",
    "routing_number": "bank_account",
    "domains": "domain",
    "ip_addresses": "ip_address",
    "social_handles": "social_handle",
    "names": "person",
    "crypto_keywords": "crypto_token",
    # Legacy / synonym merges
    "crypto_wallet": "wallet_address",
    "transaction_ids": "transaction_id",
    "transaction": "transaction_id",
    "ticket_ids": "ticket_id",
    "banks": "organization",
    "bank": "organization",
    "agencies": "agency",
    "retailers": "organization",
    "retailer": "organization",
    "handles": "social_handle",
    "tokens": "crypto_token",
    "software": "scam_indicator",
    # Unmapped display-label variants that leak from external sources
    "account": "bank_account",
}


def normalize_entity_type(raw: str) -> str:
    """Return the canonical form of an entity type.

    If *raw* is already canonical it is returned as-is.  Otherwise the
    normalization map is consulted.  Unknown types pass through unchanged
    so we don't silently drop data — but a warning should be logged by
    the caller.
    """
    if raw in ENTITY_TYPE_LABELS:
        return raw  # Already canonical
    return _ENTITY_TYPE_MAP.get(raw, raw)


# ---------------------------------------------------------------------------
# Value normalization — canonical form per entity type
# ---------------------------------------------------------------------------


def normalize_entity_value(entity_type: str, value: str) -> str:
    """Return a canonical form of *value* for the given entity type.

    Applied before DB upsert so that ``(case_id, entity_type, canonical_value)``
    dedup works correctly across formatting variants.
    """
    canonical_type = normalize_entity_type(entity_type)
    normalizer = _VALUE_NORMALIZERS.get(canonical_type)
    if normalizer is not None:
        return normalizer(value)
    # Default: collapse whitespace
    return " ".join(value.split())


def _norm_wallet(v: str) -> str:
    """Lowercase hex wallets, strip whitespace."""
    stripped = v.strip()
    if stripped.startswith("0x"):
        return stripped.lower()
    return stripped


def _norm_email(v: str) -> str:
    return v.strip().lower()


def _norm_phone(v: str) -> str:
    """Strip to digits + leading ``+``."""
    stripped = v.strip()
    digits = re.sub(r"[^\d]", "", stripped)
    if stripped.startswith("+"):
        return "+" + digits
    return digits


def _norm_url(v: str) -> str:
    """Lowercase, strip trailing slashes."""
    return v.strip().lower().rstrip("/")


def _norm_domain(v: str) -> str:
    return v.strip().lower().rstrip(".")


def _norm_person(v: str) -> str:
    """Title-case, collapse whitespace."""
    return " ".join(v.split()).title()


_VALUE_NORMALIZERS: dict[str, Callable[[str], str]] = {
    "wallet_address": _norm_wallet,
    "email_address": _norm_email,
    "phone_number": _norm_phone,
    "url": _norm_url,
    "domain": _norm_domain,
    "person": _norm_person,
    "organization": _norm_person,
    "social_handle": lambda v: v.strip().lower(),
    "contact_handle": lambda v: v.strip().lower(),
    "payment_handle": lambda v: v.strip(),
    "ip_address": lambda v: v.strip(),
    "bank_account": lambda v: v.strip(),
}


def entity_type_label(canonical: str) -> str:
    """Return a user-friendly display label for a canonical entity type."""
    if canonical in ENTITY_TYPE_LABELS:
        return ENTITY_TYPE_LABELS[canonical]
    # Fallback: replace underscores with spaces and title-case
    return canonical.replace("_", " ").title()
