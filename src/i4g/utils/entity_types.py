"""Entity type canonical definitions — the single source of truth.

Every entity that enters the database MUST use a canonical type defined here.
All write paths (LLM extraction, rule-based extraction, golden-bundle ingest,
SqlWriter, ETL scripts) call ``normalize_entity_type()`` before persisting.
Read paths should NEVER need translation — entity_type values in the DB are
already canonical.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Canonical entity types and their display labels
# ---------------------------------------------------------------------------

ENTITY_TYPE_LABELS: dict[str, str] = {
    "person": "Person",
    "organization": "Organization",
    "phone_number": "Phone Number",
    "account_number": "Account Number",
    "routing_number": "Routing Number",
    "wallet_address": "Wallet Address",
    "transaction_id": "Transaction ID",
    "ticket_id": "Ticket ID",
    "location": "Location",
    "bank": "Bank",
    "bank_account": "Bank Account",
    "agency": "Agency",
    "retailer": "Retailer",
    "social_handle": "Social Handle",
    "crypto_token": "Crypto Token",
    "scam_indicator": "Scam Indicator",
    "email_address": "Email Address",
    "url": "URL",
    "domain": "Domain",
    "ip_address": "IP Address",
    "payment_handle": "Payment Handle",
    "contact_handle": "Contact Handle",
    "software": "Software",
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
        "account_number",
        "routing_number",
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
    # Rule-based extraction keys
    "urls": "url",
    "phone_numbers": "phone_number",
    "names": "person",
    "crypto_keywords": "crypto_token",
    # Legacy / synonym merges
    "crypto_wallet": "wallet_address",
    "account_numbers": "account_number",
    "routing_numbers": "routing_number",
    "transaction_ids": "transaction_id",
    "ticket_ids": "ticket_id",
    "banks": "bank",
    "agencies": "agency",
    "retailers": "retailer",
    "handles": "social_handle",
    "tokens": "crypto_token",
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


def entity_type_label(canonical: str) -> str:
    """Return a user-friendly display label for a canonical entity type."""
    if canonical in ENTITY_TYPE_LABELS:
        return ENTITY_TYPE_LABELS[canonical]
    # Fallback: replace underscores with spaces and title-case
    return canonical.replace("_", " ").title()
