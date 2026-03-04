"""Unit tests for i4g.llm.client — provider dispatch and model resolution."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from i4g.llm.client import _resolve_model_name, build_langchain_llm, build_llm_client


# ── helpers ──────────────────────────────────────────────────────────


def _make_settings(
    provider: str = "mock",
    chat_model: str = "llama3",
    vertex_ai_model: str | None = None,
    vertex_ai_project: str | None = None,
    vertex_ai_location: str | None = "us-central1",
    ollama_base_url: str = "http://127.0.0.1:11434",
    temperature: float = 0.1,
):
    """Build a minimal Settings-like namespace for LLM tests."""
    llm = SimpleNamespace(
        provider=provider,
        chat_model=chat_model,
        vertex_ai_model=vertex_ai_model,
        vertex_ai_project=vertex_ai_project,
        vertex_ai_location=vertex_ai_location,
        ollama_base_url=ollama_base_url,
        temperature=temperature,
    )
    secrets = SimpleNamespace(project="test-project")
    return SimpleNamespace(llm=llm, secrets=secrets)


# ── _resolve_model_name ──────────────────────────────────────────────


class TestResolveModelName:
    def test_returns_chat_model_when_not_llama3(self) -> None:
        s = _make_settings(chat_model="gemini-2.5-flash")
        assert _resolve_model_name(s) == "gemini-2.5-flash"

    def test_returns_vertex_model_when_chat_is_llama3(self) -> None:
        s = _make_settings(chat_model="llama3", vertex_ai_model="gemini-2.5-flash")
        assert _resolve_model_name(s) == "gemini-2.5-flash"

    def test_returns_llama3_when_no_vertex_override(self) -> None:
        s = _make_settings(chat_model="llama3", vertex_ai_model=None)
        assert _resolve_model_name(s) == "llama3"


# ── build_llm_client ────────────────────────────────────────────────


class TestBuildLlmClient:
    def test_mock_provider(self) -> None:
        from i4g.services.classifier import MockLLMClient

        client = build_llm_client(settings=_make_settings(provider="mock"))
        assert isinstance(client, MockLLMClient)

    def test_mock_chat_model_overrides_provider(self) -> None:
        """Even if provider is 'ollama', chat_model='mock' yields MockLLMClient."""
        from i4g.services.classifier import MockLLMClient

        client = build_llm_client(settings=_make_settings(provider="ollama", chat_model="mock"))
        assert isinstance(client, MockLLMClient)

    def test_ollama_provider(self) -> None:
        from i4g.services.classifier import OllamaClient

        s = _make_settings(provider="ollama", chat_model="llama3")
        client = build_llm_client(settings=s)
        assert isinstance(client, OllamaClient)

    def test_vertex_ai_provider(self) -> None:
        from i4g.services.classifier import VertexAIClient

        s = _make_settings(provider="vertex_ai", vertex_ai_project="my-proj", chat_model="gemini-2.5-flash")
        client = build_llm_client(settings=s)
        assert isinstance(client, VertexAIClient)

    def test_vertex_ai_missing_project_raises(self) -> None:
        s = _make_settings(provider="vertex_ai", vertex_ai_project=None)
        with pytest.raises(ValueError, match="Vertex AI project not configured"):
            build_llm_client(settings=s)

    def test_unknown_provider_falls_back_to_mock(self) -> None:
        from i4g.services.classifier import MockLLMClient

        s = _make_settings(provider="unknown")
        client = build_llm_client(settings=s)
        assert isinstance(client, MockLLMClient)


# ── build_langchain_llm ─────────────────────────────────────────────


class TestBuildLangchainLlm:
    def test_mock_returns_mock_llm(self) -> None:
        from i4g.llm.client import MockLangChainLLM

        result = build_langchain_llm(settings=_make_settings(provider="mock"))
        assert isinstance(result, MockLangChainLLM)

    def test_mock_chat_model_returns_mock_llm(self) -> None:
        from i4g.llm.client import MockLangChainLLM

        result = build_langchain_llm(settings=_make_settings(provider="ollama", chat_model="mock"))
        assert isinstance(result, MockLangChainLLM)

    def test_unknown_provider_raises(self) -> None:
        s = _make_settings(provider="unknown")
        with pytest.raises(RuntimeError, match="Unsupported LLM provider"):
            build_langchain_llm(settings=s)
