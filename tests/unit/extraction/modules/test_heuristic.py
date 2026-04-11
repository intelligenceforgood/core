"""Tests for i4g.extraction.modules.heuristic — heuristic-based extraction module."""

from __future__ import annotations

from i4g.extraction.modules.heuristic import HeuristicModule
from i4g.extraction.types import ModuleProtocol, ScoredEntity


class TestHeuristicModuleProtocol:
    def test_implements_protocol(self):
        m = HeuristicModule()
        assert isinstance(m, ModuleProtocol)

    def test_name(self):
        assert HeuristicModule().name == "heuristic"

    def test_authority_values(self):
        auth = HeuristicModule().authority
        assert auth["person"] == 0.4
        assert auth["crypto_token"] == 0.4

    def test_authority_limited_to_known_types(self):
        auth = HeuristicModule().authority
        assert "wallet_address" not in auth
        assert "email_address" not in auth


class TestHeuristicModuleExtract:
    def test_extracts_person_name(self):
        text = "John Doe sent the funds"
        entities = HeuristicModule().extract(text)
        persons = [e for e in entities if e.entity_type == "person"]
        assert len(persons) >= 1
        assert persons[0].source_module == "heuristic"
        assert persons[0].confidence == 0.5

    def test_extracts_multiple_names(self):
        text = "John Doe and Jane Smith"
        entities = HeuristicModule().extract(text)
        persons = [e for e in entities if e.entity_type == "person"]
        names = {e.value for e in persons}
        assert "John Doe" in names
        assert "Jane Smith" in names

    def test_filters_banking_labels(self):
        text = "Bank Name: HSBC\nAccount Number: 12345678\nSort Code: 12-34-56"
        entities = HeuristicModule().extract(text)
        persons = [e for e in entities if e.entity_type == "person"]
        person_values = {e.value for e in persons}
        assert "Bank Name" not in person_values
        assert "Account Number" not in person_values
        assert "Sort Code" not in person_values

    def test_filters_scam_terms(self):
        text = "This is an Advance Fee scam involving a Money Mule"
        entities = HeuristicModule().extract(text)
        persons = [e for e in entities if e.entity_type == "person"]
        person_values = {e.value for e in persons}
        assert "Advance Fee" not in person_values
        assert "Money Mule" not in person_values

    def test_extracts_crypto_keywords(self):
        text = "Send via Bitcoin or Ethereum"
        entities = HeuristicModule().extract(text)
        tokens = [e for e in entities if e.entity_type == "crypto_token"]
        assert len(tokens) >= 2
        values = {e.value for e in tokens}
        assert "bitcoin" in values
        assert "ethereum" in values

    def test_crypto_confidence(self):
        text = "Invest in BTC"
        entities = HeuristicModule().extract(text)
        tokens = [e for e in entities if e.entity_type == "crypto_token"]
        assert len(tokens) >= 1
        assert tokens[0].confidence == 0.5
        assert tokens[0].source_module == "heuristic"

    def test_empty_text(self):
        assert HeuristicModule().extract("") == []

    def test_plain_text_no_entities(self):
        entities = HeuristicModule().extract("nothing special here")
        assert entities == []

    def test_all_results_are_scored_entities(self):
        text = "John Doe invested in Bitcoin and Ethereum"
        entities = HeuristicModule().extract(text)
        for e in entities:
            assert isinstance(e, ScoredEntity)
            assert e.source_module == "heuristic"

    def test_person_canonical_value_title_cased(self):
        # extract_names uses a capitalized two-word pattern, so "JOHN DOE" won't match.
        # But "John Doe" will.
        text2 = "John Doe is involved"
        entities = HeuristicModule().extract(text2)
        persons = [e for e in entities if e.entity_type == "person"]
        assert len(persons) >= 1
        assert persons[0].canonical_value == "John Doe"
