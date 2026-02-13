"""Integration tests for the RAG scam-detection pipeline (F14).

These tests exercise the full ``build_scam_detection_chain`` with a mock
LLM provider and an in-memory vector store to verify end-to-end wiring:

* Provider-agnostic LLM selection (F9)
* Structured output via ``PydanticOutputParser`` (F10)
* Citation-aware context formatting (F11)
* Few-shot golden examples injection (F12)
* Configurable prompt template (F13)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from i4g.rag.models import CitationSource, RagAssessment
from i4g.rag.pipeline import (
    _format_golden_examples,
    _format_retrieved_docs,
    _load_golden_examples,
    _load_prompt_template,
    build_scam_detection_chain,
)


# ── Helpers ──────────────────────────────────────────────────────────


class _FakeDocument:
    """Minimal stand-in for ``langchain_core.documents.Document``."""

    def __init__(self, page_content: str, metadata: dict[str, Any] | None = None) -> None:
        self.page_content = page_content
        self.metadata = metadata or {}


class _FakeRetriever:
    """Returns canned documents for any query."""

    def __init__(self, docs: list[_FakeDocument]) -> None:
        self._docs = docs

    def invoke(self, query: str) -> list[_FakeDocument]:  # noqa: ARG002
        return self._docs


class _FakeVectorStore:
    """Minimal vectorstore that yields a ``_FakeRetriever``."""

    def __init__(self, docs: list[_FakeDocument]) -> None:
        self._docs = docs

    def as_retriever(self, **kwargs: Any) -> _FakeRetriever:  # noqa: ARG002
        return _FakeRetriever(self._docs)


_VALID_ASSESSMENT = {
    "is_scam": True,
    "confidence": 0.91,
    "reasoning": "Classic crypto scam with urgent payment request.",
    "citations": [
        {"chunk_id": "src_42", "excerpt": "Send 0.5 BTC to wallet abc123."},
    ],
}


class _MockLLM:
    """LLM that always returns a valid ``RagAssessment`` JSON."""

    def invoke(self, messages: Any) -> Any:  # noqa: ARG002
        class _Resp:
            content = json.dumps(_VALID_ASSESSMENT)

        return _Resp()


# ── _format_retrieved_docs (F11) ─────────────────────────────────────


class TestFormatRetrievedDocs:
    def test_numbers_chunks_with_source_id(self) -> None:
        docs = [
            _FakeDocument("Hello world", {"source_id": "doc_A"}),
            _FakeDocument("Goodbye world", {"source_id": "doc_B"}),
        ]
        result = _format_retrieved_docs(docs)
        assert "[1] doc_A: Hello world" in result
        assert "[2] doc_B: Goodbye world" in result

    def test_falls_back_to_positional_id(self) -> None:
        docs = [_FakeDocument("No metadata")]
        result = _format_retrieved_docs(docs)
        assert "[1] chunk_1: No metadata" in result

    def test_uses_source_metadata_key(self) -> None:
        docs = [_FakeDocument("Text", {"source": "file.pdf"})]
        result = _format_retrieved_docs(docs)
        assert "[1] file.pdf: Text" in result


# ── Prompt & examples loading (F12, F13) ─────────────────────────────


class TestLoadPromptTemplate:
    def test_loads_existing_file(self, tmp_path: Path) -> None:
        f = tmp_path / "prompt.md"
        f.write_text("custom prompt {{ context }}")
        result = _load_prompt_template(f)
        assert "custom prompt" in result

    def test_fallback_when_missing(self, tmp_path: Path) -> None:
        result = _load_prompt_template(tmp_path / "nonexistent.md")
        assert "scam detection assistant" in result.lower()


class TestLoadGoldenExamples:
    def test_loads_existing_file(self, tmp_path: Path) -> None:
        f = tmp_path / "examples.json"
        f.write_text(json.dumps([{"context": "test", "question": "q", "output": {}}]))
        result = _load_golden_examples(f)
        assert len(result) == 1

    def test_returns_empty_when_missing(self, tmp_path: Path) -> None:
        result = _load_golden_examples(tmp_path / "nonexistent.json")
        assert result == []

    def test_returns_empty_on_invalid_json(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.json"
        f.write_text("not json {{{")
        result = _load_golden_examples(f)
        assert result == []


class TestFormatGoldenExamples:
    def test_empty_returns_empty_string(self) -> None:
        assert _format_golden_examples([]) == ""

    def test_formats_examples_with_headers(self) -> None:
        examples = [
            {"context": "ctx", "question": "q?", "output": {"is_scam": True}},
        ]
        result = _format_golden_examples(examples)
        assert "Example 1" in result
        assert "ctx" in result
        assert "is_scam" in result


# ── End-to-end pipeline (F9, F10, F11, F14) ──────────────────────────


class TestBuildScamDetectionChainStructured:
    """Full pipeline integration with mock LLM + fake vector store."""

    def test_returns_rag_assessment(self) -> None:
        docs = [
            _FakeDocument("Send 0.5 BTC to wallet abc123.", {"source_id": "src_42"}),
            _FakeDocument("I promise huge returns.", {"source_id": "src_43"}),
        ]
        vs = _FakeVectorStore(docs)

        with patch("i4g.rag.pipeline.build_langchain_llm", return_value=_MockLLM()):
            chain = build_scam_detection_chain(vs, structured=True)
            result = chain.invoke({"question": "Is this a scam?"})

        assert isinstance(result, RagAssessment)
        assert result.is_scam is True
        assert result.confidence == 0.91
        assert len(result.citations) == 1
        assert result.citations[0].chunk_id == "src_42"

    def test_uses_custom_prompt_and_examples(self, tmp_path: Path) -> None:
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text(
            "Custom prompt.\n"
            "{{ context }}\n{{ question }}\n"
            "{{ few_shot_examples }}\n{{ format_instructions }}"
        )
        examples_file = tmp_path / "examples.json"
        examples_file.write_text(json.dumps([
            {"context": "c", "question": "q", "output": {"is_scam": False}},
        ]))

        docs = [_FakeDocument("Test doc", {"source_id": "doc_1"})]
        vs = _FakeVectorStore(docs)

        with patch("i4g.rag.pipeline.build_langchain_llm", return_value=_MockLLM()):
            chain = build_scam_detection_chain(
                vs,
                structured=True,
                prompt_template_path=prompt_file,
                golden_examples_path=examples_file,
            )
            result = chain.invoke({"question": "test?"})

        assert isinstance(result, RagAssessment)


class TestBuildScamDetectionChainLegacy:
    """Legacy unstructured path returns raw string."""

    def test_returns_string(self) -> None:
        docs = [_FakeDocument("Some evidence.", {"source_id": "src_1"})]
        vs = _FakeVectorStore(docs)

        # Mock LLM that returns plain text for the legacy path
        class _TextLLM:
            def invoke(self, messages: Any) -> Any:  # noqa: ARG002
                class _Resp:
                    content = "This looks like a scam based on the evidence."

                return _Resp()

        with patch("i4g.rag.pipeline.build_langchain_llm", return_value=_TextLLM()):
            chain = build_scam_detection_chain(vs, structured=False)
            result = chain.invoke({"question": "Is this a scam?"})

        assert isinstance(result, str)
        assert "scam" in result.lower()
