"""Tests for ML NER label-to-entity-key mapping in i4g.ml.client."""

from __future__ import annotations

from i4g.ml.client import _NER_LABEL_TO_ENTITY_KEY
from i4g.utils.entity_types import CANONICAL_ENTITY_TYPES, normalize_entity_type


class TestNERLabelMapping:
    """Validate that every ML NER label maps to a key that normalizes correctly."""

    def test_bank_account_maps_to_bank_accounts(self):
        assert _NER_LABEL_TO_ENTITY_KEY["BANK_ACCOUNT"] == "bank_accounts"

    def test_phone_maps_to_phone_numbers(self):
        assert _NER_LABEL_TO_ENTITY_KEY["PHONE"] == "phone_numbers"

    def test_email_maps_to_email_addresses(self):
        assert _NER_LABEL_TO_ENTITY_KEY["EMAIL"] == "email_addresses"

    def test_url_maps_to_urls(self):
        assert _NER_LABEL_TO_ENTITY_KEY["URL"] == "urls"

    def test_all_mapped_keys_normalize_to_canonical(self):
        for label, key in _NER_LABEL_TO_ENTITY_KEY.items():
            canonical = normalize_entity_type(key)
            assert canonical in CANONICAL_ENTITY_TYPES, (
                f"ML NER label {label!r} -> key {key!r} -> {canonical!r} " f"is not a canonical entity type"
            )

    def test_no_contact_channels_in_mapping(self):
        """The old catch-all 'contact_channels' key should not appear."""
        assert "contact_channels" not in _NER_LABEL_TO_ENTITY_KEY.values()
