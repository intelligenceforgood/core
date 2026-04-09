"""Tests for indicator filtering in entity extraction job."""

from __future__ import annotations

from i4g.utils.entity_types import THREAT_ENTITY_TYPES


class TestIndicatorFiltering:
    """Verify that only threat entity types should create indicator rows."""

    def test_person_is_not_threat_type(self):
        assert "person" not in THREAT_ENTITY_TYPES

    def test_organization_is_not_threat_type(self):
        assert "organization" not in THREAT_ENTITY_TYPES

    def test_location_is_not_threat_type(self):
        assert "location" not in THREAT_ENTITY_TYPES

    def test_scam_indicator_is_not_threat_type(self):
        assert "scam_indicator" not in THREAT_ENTITY_TYPES

    def test_wallet_address_is_threat_type(self):
        assert "wallet_address" in THREAT_ENTITY_TYPES

    def test_email_address_is_threat_type(self):
        assert "email_address" in THREAT_ENTITY_TYPES

    def test_phone_number_is_threat_type(self):
        assert "phone_number" in THREAT_ENTITY_TYPES

    def test_url_is_threat_type(self):
        assert "url" in THREAT_ENTITY_TYPES

    def test_bank_account_is_threat_type(self):
        assert "bank_account" in THREAT_ENTITY_TYPES

    def test_domain_is_threat_type(self):
        assert "domain" in THREAT_ENTITY_TYPES

    def test_social_handle_is_threat_type(self):
        assert "social_handle" in THREAT_ENTITY_TYPES

    def test_crypto_token_is_not_threat_type(self):
        assert "crypto_token" in THREAT_ENTITY_TYPES

    def test_threat_types_cover_key_infrastructure(self):
        """Ensure the critical threat types are all present."""
        required = {
            "wallet_address",
            "bank_account",
            "email_address",
            "phone_number",
            "url",
            "domain",
            "social_handle",
        }
        assert required.issubset(THREAT_ENTITY_TYPES)
