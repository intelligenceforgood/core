"""Structured output parsing with retry for the RAG pipeline.

Uses LangChain's ``PydanticOutputParser`` to enforce JSON schema compliance.
When the LLM returns malformed output, a retry loop re-invokes the LLM with
the validation error so it can self-correct (up to ``max_retries`` attempts).

Design rationale (F10 — feature_completeness_plan.md):
    Recommendation (a) PydanticOutputParser for portability across providers,
    with Gemini structured-output mode as a future optimization for Vertex AI.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from langchain_core.output_parsers import PydanticOutputParser

from i4g.rag.models import RagAssessment

if TYPE_CHECKING:
    from langchain_core.language_models import BaseLanguageModel
    from langchain_core.prompts import ChatPromptTemplate

LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def build_assessment_parser() -> PydanticOutputParser[RagAssessment]:
    """Return a ``PydanticOutputParser`` bound to :class:`RagAssessment`.

    The parser exposes ``get_format_instructions()`` which should be injected
    into the prompt template so the LLM knows the expected JSON schema.
    """
    return PydanticOutputParser(pydantic_object=RagAssessment)


def parse_with_retry(
    raw_text: str,
    parser: PydanticOutputParser[RagAssessment],
    llm: BaseLanguageModel | Any | None = None,
    prompt: ChatPromptTemplate | None = None,
    *,
    max_retries: int = 2,
    invoke_kwargs: dict[str, Any] | None = None,
) -> RagAssessment:
    """Parse *raw_text* into a :class:`RagAssessment`, retrying on failure.

    Strategy:
    1.  Try to parse the text directly.
    2.  If parsing fails, attempt to extract a JSON object from the text
        (handles LLMs that wrap JSON in markdown fences or extra prose).
    3.  If an *llm* and *prompt* are provided, re-invoke the LLM with the
        validation error appended, asking it to fix its output.
    4.  Repeat up to *max_retries* times.

    Args:
        raw_text: Raw LLM output string.
        parser: The ``PydanticOutputParser`` to use.
        llm: Optional LangChain LLM for retry re-invocation.
        prompt: Optional prompt template for retry re-invocation.
        max_retries: Maximum number of retry attempts (default 2).
        invoke_kwargs: Additional kwargs to pass to the LLM invoke call
            during retries (e.g., ``{"context": ..., "question": ...}``).

    Returns:
        A validated ``RagAssessment`` instance.

    Raises:
        ValueError: If parsing fails after all retries.
    """
    last_error: Exception | None = None

    for attempt in range(1 + max_retries):
        try:
            return _try_parse(raw_text, parser)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            LOGGER.debug(
                "Parse attempt %d/%d failed: %s",
                attempt + 1,
                1 + max_retries,
                exc,
            )

            # If we have an LLM, ask it to fix the output
            if llm is not None and attempt < max_retries:
                raw_text = _retry_with_llm(
                    raw_text=raw_text,
                    error=exc,
                    parser=parser,
                    llm=llm,
                    prompt=prompt,
                    invoke_kwargs=invoke_kwargs or {},
                )

    raise ValueError(
        f"Failed to parse RAG output after {1 + max_retries} attempts. "
        f"Last error: {last_error}"
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Regex to detect ```json ... ``` fences
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)


def _extract_json_block(text: str) -> str:
    """Extract JSON from markdown code fences or bare JSON in surrounding prose."""
    # Try markdown code fence first
    match = _JSON_FENCE_RE.search(text)
    if match:
        return match.group(1).strip()

    # Try to find a bare JSON object
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end > brace_start:
        return text[brace_start : brace_end + 1]

    return text


def _try_parse(raw_text: str, parser: PydanticOutputParser[RagAssessment]) -> RagAssessment:
    """Attempt to parse *raw_text*, trying JSON extraction as a fallback."""
    # First try the parser directly
    try:
        return parser.parse(raw_text)
    except Exception:
        pass

    # Fallback: extract JSON block and parse
    cleaned = _extract_json_block(raw_text)
    if cleaned != raw_text:
        try:
            return parser.parse(cleaned)
        except Exception:
            pass

    # Final fallback: manual JSON parse + Pydantic validation
    try:
        data = json.loads(cleaned)
        return RagAssessment.model_validate(data)
    except Exception as exc:
        raise ValueError(f"Cannot parse LLM output as RagAssessment: {exc}") from exc


def _retry_with_llm(
    raw_text: str,
    error: Exception,
    parser: PydanticOutputParser[RagAssessment],
    llm: Any,
    prompt: ChatPromptTemplate | None,
    invoke_kwargs: dict[str, Any],
) -> str:
    """Re-invoke the LLM with the validation error asking it to fix its output."""
    fix_prompt = (
        "Your previous response could not be parsed as valid JSON.\n\n"
        f"Original output:\n{raw_text}\n\n"
        f"Error:\n{error}\n\n"
        f"Please respond with ONLY valid JSON matching this schema:\n"
        f"{parser.get_format_instructions()}\n\n"
        "Do not include any text before or after the JSON object."
    )

    try:
        from langchain_core.messages import HumanMessage

        response = llm.invoke([HumanMessage(content=fix_prompt)])
        if hasattr(response, "content"):
            return response.content
        return str(response)
    except Exception:
        LOGGER.warning("LLM retry invocation failed; returning original text", exc_info=True)
        return raw_text
