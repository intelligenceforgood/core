"""Tests for i4g.extraction.normalize — re-exported normalization functions."""

from __future__ import annotations

from i4g.extraction.normalize import (
    normalize_entity_type,
    normalize_entity_value,
    normalize_obfuscated_text,
)


class TestNormalizeReExports:
    """Verify that normalize.py re-exports work identically to entity_types.py."""

    def test_normalize_entity_type_canonical(self):
        assert normalize_entity_type("person") == "person"

    def test_normalize_entity_type_plural(self):
        assert normalize_entity_type("people") == "person"
        assert normalize_entity_type("wallet_addresses") == "wallet_address"

    def test_normalize_entity_type_unknown_passthrough(self):
        assert normalize_entity_type("unknown_type") == "unknown_type"

    def test_normalize_entity_value_wallet(self):
        result = normalize_entity_value("wallet_address", "0xAbC123")
        assert result == "0xabc123"

    def test_normalize_entity_value_email(self):
        result = normalize_entity_value("email_address", "  Alice@Example.COM  ")
        assert result == "alice@example.com"

    def test_normalize_entity_value_person(self):
        result = normalize_entity_value("person", "  john   doe  ")
        assert result == "John Doe"


class TestNormalizeObfuscatedText:
    def test_dot_obfuscation(self):
        assert "google.com" in normalize_obfuscated_text("google dot com")

    def test_at_obfuscation(self):
        assert "alice@gmail" in normalize_obfuscated_text("alice at gmail")

    def test_bracket_dot(self):
        assert "google.com" in normalize_obfuscated_text("google[dot]com")

    def test_bracket_at(self):
        assert "alice@gmail" in normalize_obfuscated_text("alice[at]gmail")

    def test_paren_dot(self):
        assert "google.com" in normalize_obfuscated_text("google(dot)com")

    def test_no_obfuscation_passthrough(self):
        text = "Normal text without obfuscation"
        assert normalize_obfuscated_text(text) == text

    def test_leetspeak_known_word(self):
        result = normalize_obfuscated_text("Visit g00gle for info")
        assert "google" in result

    def test_leetspeak_unknown_word_passthrough(self):
        # Unknown words should not be decoded
        result = normalize_obfuscated_text("Code is 4b3c")
        assert "4b3c" in result

    def test_spaced_chars_domain(self):
        result = normalize_obfuscated_text("go to g o o g l e . c o m now")
        assert "google.com" in result

    def test_combined_obfuscation(self):
        """Separator words should all resolve."""
        result = normalize_obfuscated_text("contact user at g00gle dot com")
        assert "user@" in result
        assert "google.com" in result

    def test_dash_dot_obfuscation(self):
        result = normalize_obfuscated_text("visit google -dot- com")
        assert "google.com" in result

    def test_multiple_obfuscations_in_one_text(self):
        text = "Contact alice at gmail dot com or visit b1n4nce[dot]com"
        result = normalize_obfuscated_text(text)
        assert "alice@gmail.com" in result
        assert "binance.com" in result

    def test_leetspeak_bitcoin(self):
        result = normalize_obfuscated_text("Send b1tc0in to my wallet")
        # 'b1tc0in' → leetspeak decode would be 'bitcoin' (1→i, 0→o)
        assert "bitcoin" in result
