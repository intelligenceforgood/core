"""Tests for i4g.extraction.modules.regex — regex-based extraction module."""

from __future__ import annotations

from i4g.extraction.modules.regex import RegexModule
from i4g.extraction.types import ModuleProtocol, ScoredEntity


class TestRegexModuleProtocol:
    def test_implements_protocol(self):
        m = RegexModule()
        assert isinstance(m, ModuleProtocol)

    def test_name(self):
        assert RegexModule().name == "regex"

    def test_authority_keys(self):
        auth = RegexModule().authority
        assert auth["wallet_address"] == 1.0
        assert auth["email_address"] == 1.0
        assert auth["phone_number"] == 1.0
        assert auth["url"] == 1.0
        assert auth["bank_account"] == 0.9
        assert auth["social_handle"] == 0.9

    def test_authority_does_not_claim_person(self):
        assert "person" not in RegexModule().authority

    def test_authority_does_not_claim_organization(self):
        assert "organization" not in RegexModule().authority


class TestRegexModuleExtract:
    def test_extracts_eth_wallet(self):
        text = "Pay to 0xAb5801a7D398351b8bE11C439e05C5B3259aeC9B"
        entities = RegexModule().extract(text)
        wallets = [e for e in entities if e.entity_type == "wallet_address"]
        assert len(wallets) >= 1
        assert wallets[0].source_module == "regex"
        assert wallets[0].confidence == 0.9

    def test_extracts_email(self):
        text = "Email alice@example.com for details"
        entities = RegexModule().extract(text)
        emails = [e for e in entities if e.entity_type == "email_address"]
        assert len(emails) >= 1
        assert emails[0].canonical_value == "alice@example.com"

    def test_extracts_phone_number(self):
        text = "Call +1 555-123-4567"
        entities = RegexModule().extract(text)
        phones = [e for e in entities if e.entity_type == "phone_number"]
        assert len(phones) >= 1

    def test_extracts_url(self):
        text = "Visit https://example.com/scam"
        entities = RegexModule().extract(text)
        urls = [e for e in entities if e.entity_type == "url"]
        assert len(urls) >= 1

    def test_extracts_bank_account(self):
        text = "Account number 12345678"
        entities = RegexModule().extract(text)
        accounts = [e for e in entities if e.entity_type == "bank_account"]
        assert len(accounts) >= 1
        assert accounts[0].canonical_value == "12345678"

    def test_extracts_social_handle(self):
        text = "Contact @fraudster on Telegram"
        entities = RegexModule().extract(text)
        handles = [e for e in entities if e.entity_type == "social_handle"]
        assert len(handles) >= 1

    def test_empty_text(self):
        assert RegexModule().extract("") == []

    def test_plain_text_no_entities(self):
        assert RegexModule().extract("Nothing special here") == []

    def test_all_results_are_scored_entities(self):
        text = "0xAb5801a7D398351b8bE11C439e05C5B3259aeC9B alice@example.com +1 555-123-4567"
        entities = RegexModule().extract(text)
        for e in entities:
            assert isinstance(e, ScoredEntity)
            assert e.source_module == "regex"
            assert 0 < e.confidence <= 1.0

    def test_does_not_extract_names(self):
        text = "John Doe sent Bitcoin"
        entities = RegexModule().extract(text)
        person_entities = [e for e in entities if e.entity_type == "person"]
        assert person_entities == []

    def test_complex_text(self):
        text = (
            "John Doe sent bitcoin to 0xAb5801a7D398351b8bE11C439e05C5B3259aeC9B. "
            "Contact via https://scam.site or call +1 555-888-9999. "
            "Email: fraud@evil.com Account number 87654321"
        )
        entities = RegexModule().extract(text)
        types_found = {e.entity_type for e in entities}
        assert "wallet_address" in types_found
        assert "url" in types_found
        assert "phone_number" in types_found
        assert "email_address" in types_found
        assert "bank_account" in types_found
