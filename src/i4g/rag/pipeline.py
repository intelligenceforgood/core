"""
Scam Detection RAG Pipeline (LangChain v0.2+)

This module constructs a LangChain Expression Language (LCEL)-based pipeline
that uses a provider-agnostic LLM as the reasoning component.  It retrieves
relevant documents from a vector store and evaluates whether the provided
context exhibits signs of fraud.

The pipeline enforces **structured JSON output** via a
``PydanticOutputParser`` bound to :class:`~i4g.rag.models.RagAssessment`.
If the LLM returns malformed JSON, a retry loop re-invokes the model with
the validation error (up to 2 retries) so it can self-correct.

Design is modular and composable:
    Retriever → Prompt (with format instructions + citations) → LLM → Structured Parser

Provider selection is handled by :func:`i4g.llm.client.build_langchain_llm`
which routes to Ollama, Vertex AI, or a mock LLM based on
``settings.llm.provider``.

See ``feature_completeness_plan.md`` WS-2 (F9–F14) for design rationale.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnableLambda, RunnablePassthrough

from i4g.llm.client import build_langchain_llm
from i4g.rag.models import RagAssessment
from i4g.rag.output_parser import build_assessment_parser, parse_with_retry
from i4g.settings.sections._paths import PROJECT_ROOT

LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt template loading (F13) — external .md file with {{ }} placeholders
# ---------------------------------------------------------------------------

_PROMPT_TEMPLATE_PATH = PROJECT_ROOT / "src" / "i4g" / "llm" / "prompts" / "rag_assessment.md"
_GOLDEN_EXAMPLES_PATH = PROJECT_ROOT / "src" / "i4g" / "rag" / "golden_examples.json"


def _load_prompt_template(path: Path | None = None) -> str:
    """Load the RAG prompt template from disk.

    Falls back to a minimal built-in template if the file is missing so the
    pipeline still functions during tests or minimal installs.
    """
    target = path or _PROMPT_TEMPLATE_PATH
    if target.exists():
        return target.read_text(encoding="utf-8")

    LOGGER.warning("RAG prompt template not found at %s; using built-in fallback.", target)
    return (
        "You are a scam detection assistant.\n"
        "Given the following chat or message context, "
        "decide if it shows signs of a scam. "
        "Focus on crypto and romance scams targeting seniors.\n\n"
        "Evidence Chunks:\n{{ context }}\n\n"
        "Question: {{ question }}\n\n"
        "{{ few_shot_examples }}\n"
        "{{ format_instructions }}\n"
        "Respond with ONLY the JSON object — no extra text, no markdown fences."
    )


def _load_golden_examples(path: Path | None = None) -> list[dict[str, Any]]:
    """Load RAG-specific golden examples for few-shot injection (F12)."""
    target = path or _GOLDEN_EXAMPLES_PATH
    if not target.exists():
        LOGGER.debug("RAG golden examples not found at %s; skipping few-shot.", target)
        return []
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        LOGGER.warning("Failed to load RAG golden examples from %s", target, exc_info=True)
        return []


def _format_golden_examples(examples: list[dict[str, Any]]) -> str:
    """Format golden examples into a human-readable few-shot block.

    Literal curly braces in JSON are doubled (``{{`` / ``}}``) so LangChain's
    ``ChatPromptTemplate`` does not treat them as template variables.
    """
    if not examples:
        return ""

    parts: list[str] = ["Here are some examples of how to assess scam content:\n"]
    for i, ex in enumerate(examples, 1):
        parts.append(f"### Example {i}")
        parts.append(f"**Context:**\n{ex.get('context', 'N/A')}")
        parts.append(f"**Question:** {ex.get('question', 'N/A')}")
        output_json = json.dumps(ex.get("output", {}), indent=2)
        # Escape braces for LangChain template safety
        output_json = output_json.replace("{", "{{").replace("}", "}}")
        parts.append(f"**Output:**\n```json\n{output_json}\n```\n")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Citation-aware context formatting (F11)
# ---------------------------------------------------------------------------


def _format_retrieved_docs(docs: list[Document]) -> str:
    """Format retrieved documents with numbered chunk IDs for citation.

    Each chunk is rendered as ``[n] <source_id>: <page_content>`` so the LLM
    can reference chunks in the ``citations`` array of the ``RagAssessment``.
    """
    parts: list[str] = []
    for i, doc in enumerate(docs, 1):
        # Use metadata source if available, otherwise generate a positional ID
        source_id = doc.metadata.get("source_id") or doc.metadata.get("source") or f"chunk_{i}"
        parts.append(f"[{i}] {source_id}: {doc.page_content}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Pipeline construction
# ---------------------------------------------------------------------------


def build_scam_detection_chain(
    vectorstore: Any,
    *,
    structured: bool = True,
    prompt_template_path: Path | None = None,
    golden_examples_path: Path | None = None,
) -> Any:
    """Build a RAG pipeline for scam detection using the LangChain LCEL API.

    Args:
        vectorstore: A LangChain-compatible vector store instance
            (e.g., FAISS, Chroma).
        structured: If ``True`` (default), the chain returns a validated
            :class:`RagAssessment` Pydantic model.  If ``False``, returns
            raw LLM text (legacy behaviour).
        prompt_template_path: Optional override for the prompt template file.
        golden_examples_path: Optional override for the golden examples file.

    Returns:
        A composable LCEL chain.  Accepts ``{"question": str}`` and returns
        either a ``RagAssessment`` (structured) or ``str`` (legacy).
    """
    retriever = vectorstore.as_retriever(search_kwargs={"k": 4})

    # F9: Provider-agnostic LLM — never falls back to hardcoded ChatOllama.
    # build_langchain_llm() returns MockLangChainLLM for mock provider.
    raw_llm = build_langchain_llm()

    # Ensure the LLM is a LangChain Runnable for LCEL chain composition.
    # ChatOllama / BaseChatModel already extends Runnable; custom adapters
    # (VertexLangChainAdapter, MockLangChainLLM) need wrapping.
    if isinstance(raw_llm, Runnable):
        llm = raw_llm
    else:
        llm = RunnableLambda(raw_llm.invoke)

    parser = build_assessment_parser()

    if structured:
        # F13: Load configurable prompt template
        raw_template = _load_prompt_template(prompt_template_path)

        # F12: Inject golden examples
        examples = _load_golden_examples(golden_examples_path)
        examples_block = _format_golden_examples(examples)

        # Replace {{ }} placeholders used by the .md template with
        # LangChain {variable} syntax for the ChatPromptTemplate,
        # and bake in the static parts (few-shot examples).
        lc_template = (
            raw_template.replace("{{ context }}", "{context}")
            .replace("{{ question }}", "{question}")
            .replace("{{ format_instructions }}", "{format_instructions}")
            .replace("{{ few_shot_examples }}", examples_block)
        )

        prompt = ChatPromptTemplate.from_template(template=lc_template)

        # Build a parsing step that retries on failure
        def _parse_output(raw: Any) -> RagAssessment:
            text = raw.content if hasattr(raw, "content") else str(raw)
            return parse_with_retry(
                raw_text=text,
                parser=parser,
                llm=raw_llm,
            )

        # F11: Pass docs through _format_retrieved_docs for citation IDs
        chain = (
            {
                "context": RunnablePassthrough()
                | (lambda inp: retriever.invoke(inp["question"]))
                | RunnableLambda(_format_retrieved_docs),
                "question": RunnablePassthrough() | (lambda inp: inp["question"]),
                "format_instructions": RunnablePassthrough()
                | (lambda _: parser.get_format_instructions()),
            }
            | prompt
            | llm
            | RunnableLambda(_parse_output)
        )
    else:
        # Legacy unstructured path
        legacy_template = (
            "You are a scam detection assistant.\n"
            "Given the following chat or message context, "
            "decide if it shows signs of a scam. "
            "Focus on crypto and romance scams targeting seniors.\n\n"
            "Context:\n{context}\n\nQuestion: {question}\n"
            "Answer clearly and concisely:"
        )
        prompt = ChatPromptTemplate.from_template(template=legacy_template)

        def _extract_text(response: Any) -> str:
            """Extract text from an LLM response (handles both AIMessage and custom adapters)."""
            if hasattr(response, "content"):
                return str(response.content)
            return str(response)

        chain = (
            {
                "context": RunnablePassthrough()
                | (lambda inp: retriever.invoke(inp["question"]))
                | RunnableLambda(_format_retrieved_docs),
                "question": RunnablePassthrough() | (lambda inp: inp["question"]),
            }
            | prompt
            | llm
            | RunnableLambda(_extract_text)
        )

    return chain
