"""Tests for i4g.extraction.modules.llm — LLM-based extraction module."""

from __future__ import annotations

import json

from i4g.extraction.modules.llm import LLMModule, _parse_entity_response
from i4g.extraction.types import ModuleProtocol, ScoredEntity


class _MockLLMClient:
    """Minimal mock that satisfies the LLMClient protocol."""

    def __init__(self, response: str = "{}") -> None:
        self._response = response

    def generate(self, prompt: str) -> str:
        return self._response


class _FailingLLMClient:
    def generate(self, prompt: str) -> str:
        raise RuntimeError("LLM unavailable")


class TestLLMModuleProtocol:
    def test_implements_protocol(self):
        m = LLMModule(llm_client=_MockLLMClient())
        assert isinstance(m, ModuleProtocol)

    def test_name(self):
        assert LLMModule(llm_client=_MockLLMClient()).name == "llm"

    def test_authority_keys(self):
        auth = LLMModule(llm_client=_MockLLMClient()).authority
        assert auth["person"] == 0.8
        assert auth["organization"] == 0.8
        assert auth["scam_indicator"] == 0.8
        assert auth["wallet_address"] == 0.7
        assert auth["location"] == 0.7


class TestParseEntityResponse:
    def test_valid_json(self):
        data = {"people": ["Alice"], "organizations": ["TrustWallet"]}
        result = _parse_entity_response(json.dumps(data))
        assert result["people"] == ["Alice"]

    def test_json_in_markdown(self):
        data = {"people": ["Bob"]}
        md = f"Here are the results:\n```json\n{json.dumps(data)}\n```"
        result = _parse_entity_response(md)
        assert result["people"] == ["Bob"]

    def test_invalid_json(self):
        result = _parse_entity_response("not json at all")
        assert result == {}

    def test_empty_string(self):
        result = _parse_entity_response("")
        assert result == {}

    def test_filters_non_list_values(self):
        data = {"people": ["Alice"], "invalid": "not_a_list"}
        result = _parse_entity_response(json.dumps(data))
        assert "people" in result
        assert "invalid" not in result


class TestLLMModuleExtract:
    def test_successful_extraction(self):
        response_data = {
            "people": ["Anna"],
            "organizations": ["TrustWallet"],
            "crypto_assets": ["USDT"],
            "wallet_addresses": [],
            "bank_accounts": [],
            "email_addresses": [],
            "phone_numbers": [],
            "urls": [],
            "domains": [],
            "social_handles": [],
            "locations": [],
            "scam_indicators": ["verification fee"],
        }
        llm = _MockLLMClient(json.dumps(response_data))
        module = LLMModule(llm_client=llm)
        entities = module.extract("Hi, I'm Anna from TrustWallet.")

        types = {e.entity_type for e in entities}
        assert "person" in types
        assert "organization" in types
        assert "crypto_token" in types
        assert "scam_indicator" in types

        anna = [e for e in entities if e.entity_type == "person"]
        assert len(anna) == 1
        assert anna[0].value == "Anna"
        assert anna[0].confidence == 0.7
        assert anna[0].source_module == "llm"

    def test_llm_failure_returns_empty(self):
        module = LLMModule(llm_client=_FailingLLMClient())
        entities = module.extract("Some text")
        assert entities == []

    def test_llm_returns_garbage(self):
        module = LLMModule(llm_client=_MockLLMClient("I cannot help with that."))
        entities = module.extract("Some text")
        assert entities == []

    def test_all_results_are_scored_entities(self):
        data = {"people": ["Alice"], "email_addresses": ["a@b.com"]}
        module = LLMModule(llm_client=_MockLLMClient(json.dumps(data)))
        entities = module.extract("Some text")
        for e in entities:
            assert isinstance(e, ScoredEntity)
            assert e.source_module == "llm"
            assert e.confidence == 0.7

    def test_normalizes_entity_types(self):
        data = {"people": ["Alice"], "crypto_assets": ["Bitcoin"]}
        module = LLMModule(llm_client=_MockLLMClient(json.dumps(data)))
        entities = module.extract("Some text")
        types = {e.entity_type for e in entities}
        # "people" should be normalized to "person", "crypto_assets" to "crypto_token"
        assert "person" in types
        assert "crypto_token" in types
        assert "people" not in types
        assert "crypto_assets" not in types

    def test_skips_dict_values_in_entity_lists(self):
        data = {"people": [{"name": "Alice"}]}
        module = LLMModule(llm_client=_MockLLMClient(json.dumps(data)))
        entities = module.extract("Some text")
        assert entities == []

    def test_skips_empty_values(self):
        data = {"people": ["", "  ", "Alice"]}
        module = LLMModule(llm_client=_MockLLMClient(json.dumps(data)))
        entities = module.extract("Some text")
        persons = [e for e in entities if e.entity_type == "person"]
        assert len(persons) == 1
        assert persons[0].value == "Alice"
