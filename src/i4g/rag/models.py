"""Pydantic models for RAG pipeline structured output.

These models define the contract for scam-detection RAG responses.
The ``RagAssessment`` model enforces structured JSON output from the LLM,
replacing the previous free-text ``StrOutputParser`` approach.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CitationSource(BaseModel):
    """A single citation referencing a retrieved evidence chunk."""

    chunk_id: str = Field(
        ...,
        description="Identifier of the retrieved document chunk (e.g., source document ID or index).",
    )
    excerpt: str = Field(
        ...,
        description="Short verbatim excerpt from the source that supports the assessment.",
    )


class RagAssessment(BaseModel):
    """Structured assessment returned by the scam-detection RAG pipeline.

    This model is the primary output contract.  LangChain's
    ``PydanticOutputParser`` injects the JSON schema into the prompt so the LLM
    returns a valid instance.  When parsing fails, a retry loop re-prompts the
    LLM with the validation error to self-correct.
    """

    is_scam: bool = Field(
        ...,
        description="Whether the analysed content is assessed as a scam (true) or not (false).",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score between 0.0 (no confidence) and 1.0 (certain).",
    )
    reasoning: str = Field(
        ...,
        description=(
            "Clear, concise explanation of why the content is or is not a scam, "
            "referencing specific evidence from the provided context."
        ),
    )
    citations: list[CitationSource] = Field(
        default_factory=list,
        description="List of evidence chunks that support the assessment. May be empty if no strong match.",
    )
