"""Centralized LLM client construction.

Provides :func:`build_llm_client` (simple ``generate(prompt) -> str``
interface) and :func:`build_langchain_llm` (LangChain Runnable interface)
so that provider-selection and model-resolution logic lives in exactly one
place instead of being duplicated across ``classifier.py``,
``llm_extractor.py``, and ``rag/pipeline.py``.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from i4g.settings import Settings, get_settings

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Simple (prompt-in / string-out) interface used by FraudClassifier
# ---------------------------------------------------------------------------


class LLMClient(Protocol):
    """Protocol for simple prompt-in / string-out LLM interactions."""

    def generate(self, prompt: str) -> str:  # pragma: no cover
        """Generate text from a prompt."""
        ...


def build_llm_client(*, settings: Settings | None = None) -> LLMClient:
    """Return a simple ``LLMClient`` based on the configured provider.

    The client exposes only ``generate(prompt) -> str``.

    Args:
        settings: Optional pre-loaded settings; defaults to ``get_settings()``.

    Returns:
        An ``LLMClient`` implementation for the current provider.
    """
    from i4g.services.classifier import MockLLMClient, OllamaClient, VertexAIClient

    s = settings or get_settings()
    provider = s.llm.provider

    if provider == "mock" or s.llm.chat_model == "mock":
        return MockLLMClient()

    if provider == "ollama":
        return OllamaClient(
            base_url=s.llm.ollama_base_url,
            model=s.llm.chat_model,
        )

    if provider in ("vertex_ai", "gemini"):
        if not s.llm.vertex_ai_project:
            raise ValueError("Vertex AI project not configured (settings.llm.vertex_ai_project).")
        model_name = s.llm.chat_model
        return VertexAIClient(
            project=s.llm.vertex_ai_project,
            location=s.llm.vertex_ai_location or "us-central1",
            model_name=model_name,
        )

    LOGGER.warning("Unknown LLM provider '%s'; falling back to mock.", provider)
    return MockLLMClient()


# ---------------------------------------------------------------------------
# LangChain-compatible interface used by AccountEntityExtractor & RAG
# ---------------------------------------------------------------------------


def build_langchain_llm(*, settings: Settings | None = None) -> Any:
    """Return a LangChain-compatible LLM based on the configured provider.

    The returned object supports ``.invoke(messages)`` (LangChain Runnable
    protocol).

    Args:
        settings: Optional pre-loaded settings; defaults to ``get_settings()``.

    Returns:
        A LangChain chat model object.  For the mock provider, returns a
        :class:`MockLangChainLLM` that produces a valid ``RagAssessment``
        JSON string so callers never need a ``None`` fallback.
    """
    s = settings or get_settings()
    provider = s.llm.provider

    if provider == "mock" or s.llm.chat_model == "mock":
        return MockLangChainLLM()

    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=s.llm.chat_model,
            base_url=s.llm.ollama_base_url,
            temperature=s.llm.temperature,
        )

    if provider in ("vertex_ai", "gemini"):
        return _build_vertex_langchain(s)

    raise RuntimeError(
        f"Unsupported LLM provider '{provider}'. "
        "Configure 'ollama', 'gemini' (or 'vertex_ai'), or 'mock' via I4G_LLM__PROVIDER."
    )


# ---------------------------------------------------------------------------
# Mock LangChain LLM — returns deterministic RagAssessment JSON
# ---------------------------------------------------------------------------

_MOCK_ASSESSMENT_JSON = json.dumps(
    {
        "is_scam": False,
        "confidence": 0.5,
        "reasoning": "Mock LLM: unable to perform real analysis.",
        "citations": [],
    }
)


class MockLangChainLLM:
    """A LangChain-compatible mock that returns a canned ``RagAssessment`` JSON.

    Used when ``settings.llm.provider == "mock"`` so that the RAG pipeline
    (and any other LangChain consumer) can run end-to-end without a live LLM.
    """

    def invoke(self, messages: Any) -> Any:  # noqa: ARG002
        """Return a canned response wrapped in a ``content`` attribute."""

        class _MockResponse:
            content = _MOCK_ASSESSMENT_JSON

        return _MockResponse()


def _build_vertex_langchain(settings: Settings) -> Any:
    """Build a Vertex AI adapter matching the LangChain Runnable ``.invoke()`` interface.

    Uses the ``google-genai`` unified SDK (``genai.Client(vertexai=True)``).
    """
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise ImportError(
            "Vertex AI requires 'google-genai'. " "Install with: pip install 'google-genai>=1.0.0,<2.0'"
        ) from exc

    project = settings.llm.vertex_ai_project or settings.secrets.project
    location = settings.llm.vertex_ai_location or "us-central1"
    model_name = settings.llm.chat_model

    client = genai.Client(vertexai=True, project=project, location=location)
    LOGGER.info("Initialized Vertex AI LangChain adapter", extra={"project": project, "model": model_name})

    class _VertexLangChainAdapter:
        """Wraps ``genai.Client`` to satisfy the LangChain Runnable interface."""

        def __init__(self, genai_client: Any, model: str, temperature: float) -> None:
            self._client = genai_client
            self._model_name = model
            self._temperature = temperature

        def invoke(self, messages: Any) -> Any:
            """Convert LangChain messages to a prompt and call Vertex AI."""
            if isinstance(messages, list):
                parts = []
                for msg in messages:
                    if hasattr(msg, "content"):
                        role = "System" if "System" in msg.__class__.__name__ else "User"
                        parts.append(f"{role}: {msg.content}")
                    else:
                        parts.append(str(msg))
                full_prompt = "\n\n".join(parts)
            else:
                full_prompt = str(messages)

            config = types.GenerateContentConfig(
                temperature=self._temperature,
                response_mime_type="application/json",
            )
            try:
                response = self._client.models.generate_content(
                    model=self._model_name,
                    contents=full_prompt,
                    config=config,
                )
            except Exception:
                LOGGER.exception("Vertex AI generation failed")
                raise

            class _MessageResponse:
                def __init__(self, text: str) -> None:
                    self.content = text

            return _MessageResponse(response.text)

    return _VertexLangChainAdapter(
        genai_client=client,
        model=model_name,
        temperature=settings.llm.temperature,
    )
