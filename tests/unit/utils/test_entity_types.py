"""Tests for i4g.utils.entity_types — normalization map completeness."""

from __future__ import annotations

from i4g.extraction.ner_rules import extract_entities as rule_extract_entities
from i4g.utils.entity_types import (
    _ENTITY_TYPE_MAP,
    CANONICAL_ENTITY_TYPES,
    THREAT_ENTITY_TYPES,
    normalize_entity_type,
)


class TestNormalizationMapCompleteness:
    """Every key returned by rule_extract_entities() must normalize to a canonical type."""

    def test_all_rule_extract_keys_normalize_to_canonical(self):
        result = rule_extract_entities("dummy text")
        for key in result:
            canonical = normalize_entity_type(key)
            assert canonical in CANONICAL_ENTITY_TYPES, (
                f"Rule-based key {key!r} normalizes to {canonical!r} " f"which is not in CANONICAL_ENTITY_TYPES"
            )

    def test_all_map_values_are_canonical(self):
        for raw, canonical in _ENTITY_TYPE_MAP.items():
            assert canonical in CANONICAL_ENTITY_TYPES, f"Map entry {raw!r} -> {canonical!r} is not a canonical type"

    def test_threat_types_are_canonical(self):
        for t in THREAT_ENTITY_TYPES:
            assert t in CANONICAL_ENTITY_TYPES, f"Threat type {t!r} is not in CANONICAL_ENTITY_TYPES"

    def test_normalize_idempotent_for_canonical(self):
        for canonical in CANONICAL_ENTITY_TYPES:
            assert normalize_entity_type(canonical) == canonical

    def test_normalize_known_variants(self):
        assert normalize_entity_type("people") == "person"
        assert normalize_entity_type("organizations") == "organization"
        assert normalize_entity_type("wallet_addresses") == "wallet_address"
        assert normalize_entity_type("urls") == "url"
        assert normalize_entity_type("phone_numbers") == "phone_number"
        assert normalize_entity_type("email_addresses") == "email_address"
        assert normalize_entity_type("emails") == "email_address"
        assert normalize_entity_type("bank_accounts") == "bank_account"
        assert normalize_entity_type("bank_account") == "bank_account"
        assert normalize_entity_type("domains") == "domain"
        assert normalize_entity_type("ip_addresses") == "ip_address"
        assert normalize_entity_type("social_handles") == "social_handle"
        assert normalize_entity_type("contact_channels") == "contact_handle"
        assert normalize_entity_type("crypto_assets") == "crypto_token"

    def test_unknown_type_passes_through(self):
        assert normalize_entity_type("completely_unknown") == "completely_unknown"
