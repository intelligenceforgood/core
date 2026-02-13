"""Tests for the scam-detection RAG pipeline (structured + legacy modes).

Note: comprehensive pipeline integration tests live in
``tests/unit/rag/test_pipeline.py`` (F14).  These tests predated the WS-2
changes and are kept as additional coverage.
"""

import json
from typing import Any
from unittest.mock import patch

from i4g.rag.models import RagAssessment
from i4g.rag.pipeline import build_scam_detection_chain


class _FakeDoc:
    def __init__(self, text: str, metadata: dict[str, Any] | None = None) -> None:
        self.page_content = text
        self.metadata = metadata or {}


class _FakeRetriever:
    def invoke(self, query: str) -> list[_FakeDoc]:
        return [_FakeDoc("This looks like a crypto scam.", {"source_id": "doc_1"})]


class _FakeVectorStore:
    def as_retriever(self, **kwargs: Any) -> _FakeRetriever:
        return _FakeRetriever()


class _MockTextLLM:
    """Mock LLM returning plain text (legacy path)."""

    def invoke(self, messages: Any) -> Any:
        class _Resp:
            content = "Likely a crypto scam."

        return _Resp()


class _MockStructuredLLM:
    """Mock LLM returning valid RagAssessment JSON."""

    def invoke(self, messages: Any) -> Any:
        class _Resp:
            content = json.dumps(
                {
                    "is_scam": True,
                    "confidence": 0.92,
                    "reasoning": "Message contains typical crypto scam indicators.",
                    "citations": [
                        {"chunk_id": "doc_1", "excerpt": "Send BTC to this wallet."},
                    ],
                }
            )

        return _Resp()


def test_scam_detection_chain_legacy_unstructured():
    """Ensure legacy (unstructured) pipeline composes correctly and returns a string."""
    with patch("i4g.rag.pipeline.build_langchain_llm", return_value=_MockTextLLM()):
        chain = build_scam_detection_chain(_FakeVectorStore(), structured=False)
        response = chain.invoke({"question": "Is this message fraudulent?"})

    assert isinstance(response, str)
    assert "scam" in response.lower()


def test_scam_detection_chain_structured():
    """Structured pipeline returns a validated RagAssessment."""
    with patch("i4g.rag.pipeline.build_langchain_llm", return_value=_MockStructuredLLM()):
        chain = build_scam_detection_chain(_FakeVectorStore(), structured=True)
        response = chain.invoke({"question": "Is this message fraudulent?"})

    assert isinstance(response, RagAssessment)
    assert response.is_scam is True
    assert 0.0 <= response.confidence <= 1.0
    assert len(response.reasoning) > 0
    assert len(response.citations) == 1
    assert response.citations[0].chunk_id == "doc_1"
