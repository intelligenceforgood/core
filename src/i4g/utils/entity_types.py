"""Entity type normalization — singular, consistent naming."""

from __future__ import annotations

# Maps raw (often LLM-extracted) entity types to canonical singular forms.
# Add entries here when new inconsistent types appear in ingested data.
_ENTITY_TYPE_MAP: dict[str, str] = {
    # Plural → singular
    "people": "person",
    "organizations": "organization",
    "phone_numbers": "phone_number",
    "account_numbers": "account_number",
    "routing_numbers": "routing_number",
    "wallet_addresses": "crypto_wallet",
    "transaction_ids": "transaction_id",
    "ticket_ids": "ticket_id",
    "locations": "location",
    "banks": "bank",
    "agencies": "agency",
    "retailers": "retailer",
    # Synonym merges
    "crypto_assets": "crypto_wallet",
    # Ambiguous → descriptive
    "handles": "social_handle",
    "tokens": "crypto_token",
    "scam_indicators": "scam_indicator",
}

# Reverse map: canonical → all raw types that map to it
_REVERSE_MAP: dict[str, list[str]] = {}
for _raw, _canonical in _ENTITY_TYPE_MAP.items():
    _REVERSE_MAP.setdefault(_canonical, [_canonical]).append(_raw)
# Include identity mappings for types not in the map
for _canonical in _REVERSE_MAP:
    if _canonical not in _REVERSE_MAP[_canonical]:
        _REVERSE_MAP[_canonical].insert(0, _canonical)


def normalize_entity_type(raw: str) -> str:
    """Return the canonical singular form of an entity type."""
    return _ENTITY_TYPE_MAP.get(raw, raw)


def expand_entity_type(canonical: str) -> list[str]:
    """Return all raw DB types that map to a canonical type.

    Used for SQL ``WHERE entity_type IN (...)`` queries so that filtering
    by the normalized name matches all underlying raw variants.
    """
    return _REVERSE_MAP.get(canonical, [canonical])
