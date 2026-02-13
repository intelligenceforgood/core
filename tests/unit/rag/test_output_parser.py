"""Unit tests for i4g.rag.output_parser — structured parsing with retry."""

from __future__ import annotations

import json

import pytest

from i4g.rag.models import RagAssessment
from i4g.rag.output_parser import (
    _extract_json_block,
    build_assessment_parser,
    parse_with_retry,
)


# ── Fixtures ─────────────────────────────────────────────────────────

VALID_ASSESSMENT = {
    "is_scam": True,
    "confidence": 0.85,
    "reasoning": "The message asks for Bitcoin payment — a classic crypto scam pattern.",
    "citations": [
        {"chunk_id": "src_42", "excerpt": "Please send 0.5 BTC to wallet abc123."},
    ],
}

NOT_SCAM_ASSESSMENT = {
    "is_scam": False,
    "confidence": 0.95,
    "reasoning": "The message is a legitimate customer support inquiry with no scam indicators.",
    "citations": [],
}


# ── build_assessment_parser ──────────────────────────────────────────


class TestBuildAssessmentParser:
    def test_returns_parser_with_format_instructions(self) -> None:
        parser = build_assessment_parser()
        instructions = parser.get_format_instructions()
        assert "is_scam" in instructions
        assert "confidence" in instructions
        assert "reasoning" in instructions

    def test_parser_parses_valid_json(self) -> None:
        parser = build_assessment_parser()
        result = parser.parse(json.dumps(VALID_ASSESSMENT))
        assert isinstance(result, RagAssessment)
        assert result.is_scam is True
        assert result.confidence == 0.85


# ── _extract_json_block ──────────────────────────────────────────────


class TestExtractJsonBlock:
    def test_extracts_from_markdown_fence(self) -> None:
        text = "Here's the analysis:\n```json\n{\"is_scam\": true}\n```\nDone."
        assert _extract_json_block(text) == '{"is_scam": true}'

    def test_extracts_from_fence_without_json_label(self) -> None:
        text = "```\n{\"is_scam\": false}\n```"
        assert _extract_json_block(text) == '{"is_scam": false}'

    def test_extracts_bare_json_from_surrounding_prose(self) -> None:
        text = 'Based on my analysis: {"is_scam": true, "confidence": 0.9} That is my answer.'
        result = _extract_json_block(text)
        assert result.startswith("{")
        assert '"is_scam": true' in result

    def test_returns_original_text_when_no_json(self) -> None:
        text = "No JSON here at all."
        assert _extract_json_block(text) == text


# ── parse_with_retry ─────────────────────────────────────────────────


class TestParseWithRetry:
    def test_parses_clean_json(self) -> None:
        parser = build_assessment_parser()
        result = parse_with_retry(json.dumps(VALID_ASSESSMENT), parser)
        assert result.is_scam is True
        assert result.confidence == 0.85

    def test_parses_not_scam(self) -> None:
        parser = build_assessment_parser()
        result = parse_with_retry(json.dumps(NOT_SCAM_ASSESSMENT), parser)
        assert result.is_scam is False
        assert result.confidence == 0.95
        assert result.citations == []

    def test_parses_json_in_markdown_fence(self) -> None:
        parser = build_assessment_parser()
        wrapped = f"```json\n{json.dumps(VALID_ASSESSMENT)}\n```"
        result = parse_with_retry(wrapped, parser)
        assert result.is_scam is True

    def test_parses_json_with_surrounding_prose(self) -> None:
        parser = build_assessment_parser()
        text = f"Here is my analysis:\n{json.dumps(VALID_ASSESSMENT)}\nEnd of analysis."
        result = parse_with_retry(text, parser)
        assert result.is_scam is True

    def test_raises_on_completely_invalid_text(self) -> None:
        parser = build_assessment_parser()
        with pytest.raises(ValueError, match="Failed to parse RAG output"):
            parse_with_retry("This is not JSON at all.", parser, max_retries=0)

    def test_raises_on_invalid_confidence_range(self) -> None:
        parser = build_assessment_parser()
        bad = {**VALID_ASSESSMENT, "confidence": 1.5}
        with pytest.raises(ValueError, match="Failed to parse RAG output"):
            parse_with_retry(json.dumps(bad), parser, max_retries=0)

    def test_raises_on_missing_required_field(self) -> None:
        parser = build_assessment_parser()
        incomplete = {"is_scam": True}  # missing confidence, reasoning
        with pytest.raises(ValueError, match="Failed to parse RAG output"):
            parse_with_retry(json.dumps(incomplete), parser, max_retries=0)

    def test_retry_with_mock_llm_fixes_output(self) -> None:
        """When initial parse fails, the retry LLM returns valid JSON."""
        parser = build_assessment_parser()

        class _FixingLLM:
            def invoke(self, messages):
                class _Resp:
                    content = json.dumps(VALID_ASSESSMENT)

                return _Resp()

        result = parse_with_retry(
            "garbage text",
            parser,
            llm=_FixingLLM(),
            max_retries=1,
        )
        assert result.is_scam is True
        assert result.confidence == 0.85

    def test_retry_exhausted_raises(self) -> None:
        """When even the retry LLM returns bad output, we get ValueError."""
        parser = build_assessment_parser()

        class _BrokenLLM:
            def invoke(self, messages):
                class _Resp:
                    content = "still garbage"

                return _Resp()

        with pytest.raises(ValueError, match="Failed to parse RAG output"):
            parse_with_retry(
                "garbage text",
                parser,
                llm=_BrokenLLM(),
                max_retries=1,
            )


# ── RagAssessment model validation ──────────────────────────────────


class TestRagAssessmentModel:
    def test_valid_assessment(self) -> None:
        a = RagAssessment(**VALID_ASSESSMENT)
        assert a.is_scam is True
        assert len(a.citations) == 1

    def test_confidence_bounds(self) -> None:
        with pytest.raises(Exception):
            RagAssessment(is_scam=True, confidence=-0.1, reasoning="test")
        with pytest.raises(Exception):
            RagAssessment(is_scam=True, confidence=1.01, reasoning="test")

    def test_empty_citations_default(self) -> None:
        a = RagAssessment(is_scam=False, confidence=0.5, reasoning="Neutral.")
        assert a.citations == []

    def test_serialization_roundtrip(self) -> None:
        a = RagAssessment(**VALID_ASSESSMENT)
        data = json.loads(a.model_dump_json())
        b = RagAssessment.model_validate(data)
        assert a == b
