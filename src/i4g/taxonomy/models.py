"""Taxonomy data models."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ScoredLabel(BaseModel):
    """A single classification label with a confidence score."""

    label: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    explanation: Optional[str] = None


class FraudClassificationResult(BaseModel):
    """The complete classification result across all axes."""

    intent: List[ScoredLabel] = Field(default_factory=list)
    channel: List[ScoredLabel] = Field(default_factory=list)
    techniques: List[ScoredLabel] = Field(default_factory=list)
    actions: List[ScoredLabel] = Field(default_factory=list)
    persona: List[ScoredLabel] = Field(default_factory=list)

    explanation: Optional[str] = Field(
        default=None, description="Human-readable explanation of the classification."
    )
    few_shot_examples: List[Dict[str, Any]] = Field(
        default_factory=list, description="Relevant examples used for few-shot prompting."
    )

    risk_score: float = Field(0.0, ge=0.0, le=100.0, description="Calculated risk score (0-100)")
    taxonomy_version: str = Field(default="1.0", description="Version of the taxonomy used.")

# Alias for backward compatibility or TDD alignment
ClassificationResult = FraudClassificationResult

class AnalystFeedbackRequest(BaseModel):
    """Feedback provided by an analyst regarding a fraud classification."""

    original_classification: Optional[FraudClassificationResult] = None
    corrected_classification: FraudClassificationResult
    notes: Optional[str] = None
    taxonomy_version: str
