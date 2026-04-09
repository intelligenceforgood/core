"""Tests for i4g.extraction.semantic_ner — LLM-based semantic NER with fallback."""

from __future__ import annotations

from unittest.mock import MagicMock

from i4g.extraction.semantic_ner import (
    _add_confidence_scores,
    _format_chat_prompt,
    _format_few_shots,
    _merge_results,
    _safe_parse_json,
    extract_semantic_entities,
)

# ---------------------------------------------------------------------------
# _safe_parse_json
# ---------------------------------------------------------------------------


class TestSafeParseJson:
    def test_valid_json(self):
        result = _safe_parse_json('{"people": ["Alice"], "organizations": []}')
        assert result["people"] == ["Alice"]

    def test_json_embedded_in_text(self):
        text = 'Here is the result: {"people": ["Bob"]} end.'
        result = _safe_parse_json(text)
        assert result.get("people") == ["Bob"]

    def test_invalid_json_returns_raw_output(self):
        result = _safe_parse_json("This is not JSON at all")
        assert "raw_output" in result

    def test_empty_string(self):
        result = _safe_parse_json("")
        assert "raw_output" in result


# ---------------------------------------------------------------------------
# _merge_results
# ---------------------------------------------------------------------------


class TestMergeResults:
    def test_merges_and_deduplicates(self):
        llm = {"people": ["Alice", "Bob"], "organizations": ["Acme"]}
        rule = {"people": ["Bob", "Charlie"], "wallet_addresses": ["0xABC"]}
        merged = _merge_results(llm, rule)
        assert sorted(merged["people"]) == ["Alice", "Bob", "Charlie"]
        assert merged["organizations"] == ["Acme"]

    def test_empty_inputs(self):
        merged = _merge_results({}, {})
        # Should still have all entity keys from _ENTITY_KEYS
        assert "people" in merged
        assert merged["people"] == []

    def test_non_list_values_treated_as_empty(self):
        llm = {"people": "not_a_list"}
        rule = {"people": ["Alice"]}
        merged = _merge_results(llm, rule)
        assert "Alice" in merged["people"]


# ---------------------------------------------------------------------------
# _add_confidence_scores
# ---------------------------------------------------------------------------


class TestAddConfidenceScores:
    def test_adds_scores_to_list_values(self):
        result = {"people": ["Alice", "Bob"]}
        scored = _add_confidence_scores(result, base_score=0.8)
        assert len(scored["people"]) == 2
        assert scored["people"][0] == {"value": "Alice", "confidence": 0.8}
        assert scored["people"][1] == {"value": "Bob", "confidence": 0.8}

    def test_non_list_values_passed_through(self):
        result = {"raw_output": "some text"}
        scored = _add_confidence_scores(result)
        assert scored["raw_output"] == "some text"

    def test_default_base_score(self):
        result = {"people": ["X"]}
        scored = _add_confidence_scores(result)
        assert scored["people"][0]["confidence"] == 0.7


# ---------------------------------------------------------------------------
# _format_few_shots / _format_chat_prompt
# ---------------------------------------------------------------------------


class TestPromptFormatting:
    def test_format_few_shots_returns_string(self):
        shots = _format_few_shots()
        assert isinstance(shots, str)
        assert "Example Input:" in shots

    def test_format_chat_prompt_includes_text(self):
        prompt = _format_chat_prompt("Suspicious text about bitcoin")
        assert "Suspicious text about bitcoin" in prompt
        assert "JSON" in prompt  # Prompt should mention JSON output


# ---------------------------------------------------------------------------
# extract_semantic_entities (main entrypoint)
# ---------------------------------------------------------------------------


class TestExtractSemanticEntities:
    def test_successful_llm_extraction(self):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = (
            '{"people": ["Alice"], "organizations": ["Acme"], '
            '"crypto_assets": [], "wallet_addresses": [], '
            '"bank_accounts": [], '
            '"email_addresses": [], "phone_numbers": [], "urls": [], '
            '"domains": [], "social_handles": [], '
            '"locations": [], "scam_indicators": []}'
        )
        result = extract_semantic_entities("Alice works at Acme", mock_llm)
        # Should have scored entities
        assert any(item["value"] == "Alice" for item in result["people"])
        mock_llm.invoke.assert_called_once()

    def test_llm_returns_garbage_falls_back_to_rules(self):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = "I cannot provide that information."
        text = "Send bitcoin to 0xAb5801a7D398351b8bE11C439e05C5B3259aeC9B"
        result = extract_semantic_entities(text, mock_llm)
        # Rule-based extractor should still find the wallet
        assert "fallback_info" in result
        wallet_values = [item["value"] for item in result.get("wallet_addresses", [])]
        assert any("0x" in w for w in wallet_values)

    def test_llm_raises_exception_falls_back_to_rules(self):
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = RuntimeError("Connection failed")
        text = "John Doe says bitcoin is great"
        result = extract_semantic_entities(text, mock_llm)
        assert "fallback_info" in result
        assert "llm_invocation_error" in result["fallback_info"]["reason"]

    def test_llm_invalid_json_with_embedded_object(self):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = (
            'Sure, here is the extraction: {"people": ["Eve"], "organizations": [], '
            '"crypto_assets": [], "wallet_addresses": [], "contact_channels": [], '
            '"locations": [], "scam_indicators": ["phishing"]} That is what I found.'
        )
        result = extract_semantic_entities("Eve ran a phishing scheme", mock_llm)
        assert any(item["value"] == "Eve" for item in result.get("people", []))
