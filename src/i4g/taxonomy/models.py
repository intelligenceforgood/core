from typing import List, Optional
from pydantic import BaseModel, Field, field_validator
from i4g.taxonomy.enums import (
    ScamIntent,
    DeliveryChannel,
    SocialEngineeringTechnique,
    RequestedAction,
    ClaimedPersona,
)

class ScoredLabel(BaseModel):
    label: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    explanation: Optional[str] = None

class FraudClassificationResult(BaseModel):
    intent: List[ScoredLabel] = Field(default_factory=list)
    channel: List[ScoredLabel] = Field(default_factory=list)
    techniques: List[ScoredLabel] = Field(default_factory=list)
    actions: List[ScoredLabel] = Field(default_factory=list)
    persona: List[ScoredLabel] = Field(default_factory=list)
    risk_score: float = Field(0.0, ge=0.0, le=100.0, description="Calculated risk score (0-100)")
    taxonomy_version: str

    @field_validator("intent")
    @classmethod
    def validate_intent(cls, v: List[ScoredLabel]) -> List[ScoredLabel]:
        valid_labels = set(item.value for item in ScamIntent)
        for item in v:
            if item.label not in valid_labels:
                raise ValueError(f"Invalid intent label: {item.label}. Must be one of {valid_labels}")
        return v

    @field_validator("channel")
    @classmethod
    def validate_channel(cls, v: List[ScoredLabel]) -> List[ScoredLabel]:
        valid_labels = set(item.value for item in DeliveryChannel)
        for item in v:
            if item.label not in valid_labels:
                raise ValueError(f"Invalid channel label: {item.label}. Must be one of {valid_labels}")
        return v

    @field_validator("techniques")
    @classmethod
    def validate_techniques(cls, v: List[ScoredLabel]) -> List[ScoredLabel]:
        valid_labels = set(item.value for item in SocialEngineeringTechnique)
        for item in v:
            if item.label not in valid_labels:
                raise ValueError(f"Invalid technique label: {item.label}. Must be one of {valid_labels}")
        return v

    @field_validator("actions")
    @classmethod
    def validate_actions(cls, v: List[ScoredLabel]) -> List[ScoredLabel]:
        valid_labels = set(item.value for item in RequestedAction)
        for item in v:
            if item.label not in valid_labels:
                raise ValueError(f"Invalid action label: {item.label}. Must be one of {valid_labels}")
        return v

    @field_validator("persona")
    @classmethod
    def validate_persona(cls, v: List[ScoredLabel]) -> List[ScoredLabel]:
        valid_labels = set(item.value for item in ClaimedPersona)
        for item in v:
            if item.label not in valid_labels:
                raise ValueError(f"Invalid persona label: {item.label}. Must be one of {valid_labels}")
        return v


class AnalystFeedbackRequest(BaseModel):
    """Feedback provided by an analyst regarding a fraud classification."""
    original_classification: Optional[FraudClassificationResult] = None
    corrected_classification: FraudClassificationResult
    notes: Optional[str] = None
    taxonomy_version: str

