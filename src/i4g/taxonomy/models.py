"""Taxonomy data models."""

from typing import Any

from pydantic import BaseModel, Field, field_validator

from i4g.taxonomy.enums import (
    ClaimedPersona,
    DeliveryChannel,
    RequestedAction,
    ScamIntent,
    SocialEngineeringTechnique,
)


class ScoredLabel(BaseModel):
    """A single classification label with a confidence score."""

    label: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    explanation: str | None = None


class FraudClassificationResult(BaseModel):
    """The complete classification result across all axes."""

    intent: list[ScoredLabel] = Field(default_factory=list)
    channel: list[ScoredLabel] = Field(default_factory=list)
    techniques: list[ScoredLabel] = Field(default_factory=list)
    actions: list[ScoredLabel] = Field(default_factory=list)
    persona: list[ScoredLabel] = Field(default_factory=list)

    explanation: str | None = Field(default=None, description="Human-readable explanation of the classification.")
    few_shot_examples: list[dict[str, Any]] = Field(
        default_factory=list, description="Relevant examples used for few-shot prompting."
    )

    risk_score: float = Field(0.0, ge=0.0, le=100.0, description="Calculated risk score (0-100)")
    taxonomy_version: str = Field(default="1.0", description="Version of the taxonomy used.")

    @field_validator("intent")
    @classmethod
    def validate_intent(cls, v: list[ScoredLabel]) -> list[ScoredLabel]:
        valid_values = {e.value for e in ScamIntent}
        for item in v:
            if item.label not in valid_values:
                raise ValueError(f"Invalid intent label: {item.label}. Must be one of {valid_values}")
        return v

    @field_validator("channel")
    @classmethod
    def validate_channel(cls, v: list[ScoredLabel]) -> list[ScoredLabel]:
        valid_values = {e.value for e in DeliveryChannel}
        for item in v:
            if item.label not in valid_values:
                raise ValueError(f"Invalid channel label: {item.label}. Must be one of {valid_values}")
        return v

    @field_validator("techniques")
    @classmethod
    def validate_techniques(cls, v: list[ScoredLabel]) -> list[ScoredLabel]:
        valid_values = {e.value for e in SocialEngineeringTechnique}
        for item in v:
            if item.label not in valid_values:
                raise ValueError(f"Invalid technique label: {item.label}. Must be one of {valid_values}")
        return v

    @field_validator("actions")
    @classmethod
    def validate_actions(cls, v: list[ScoredLabel]) -> list[ScoredLabel]:
        valid_values = {e.value for e in RequestedAction}
        for item in v:
            if item.label not in valid_values:
                raise ValueError(f"Invalid action label: {item.label}. Must be one of {valid_values}")
        return v

    @field_validator("persona")
    @classmethod
    def validate_persona(cls, v: list[ScoredLabel]) -> list[ScoredLabel]:
        valid_values = {e.value for e in ClaimedPersona}
        for item in v:
            if item.label not in valid_values:
                raise ValueError(f"Invalid persona label: {item.label}. Must be one of {valid_values}")
        return v


# Alias for backward compatibility or TDD alignment
ClassificationResult = FraudClassificationResult


class AnalystFeedbackRequest(BaseModel):
    """Feedback provided by an analyst regarding a fraud classification."""

    original_classification: FraudClassificationResult | None = None
    corrected_classification: FraudClassificationResult
    notes: str | None = None
    taxonomy_version: str
