"""Pydantic models supporting the account list extraction workflow."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class IndicatorCategory(str, Enum):
    """Supported financial indicator categories."""

    BANK = "bank"
    CRYPTO = "crypto"
    PAYMENTS = "payments"
    IP = "ip"
    BROWSER = "browser"
    ASN = "asn"


class SourceDocument(BaseModel):
    """Metadata and content for a case document passed to the LLM."""

    case_id: str
    content: str
    dataset: str | None = None
    title: str | None = None
    classification: str | None = None
    created_at: datetime | None = None
    score: float | None = None
    excerpt: str | None = None


class FinancialIndicator(BaseModel):
    """Normalized financial indicator returned by the extractor."""

    category: str
    item: str
    type: str
    number: str
    source_case_id: str | None = None
    metadata: dict[str, Any] | None = None


class AccountListRequest(BaseModel):
    """Incoming request for account list extraction."""

    start_time: datetime | None = None
    end_time: datetime | None = None
    categories: list[str] = Field(default_factory=list)
    top_k: int = Field(default=100, ge=1, le=500)
    include_sources: bool = Field(default=True)
    output_formats: list[str] = Field(default_factory=list)

    @field_validator("categories", mode="after")
    @classmethod
    def _normalize_categories(cls, value: list[str]) -> list[str]:
        if not value:
            return [
                IndicatorCategory.BANK.value,
                IndicatorCategory.CRYPTO.value,
                IndicatorCategory.PAYMENTS.value,
            ]
        normalized = [item.lower().strip() for item in value if item]
        return [item for item in normalized if item]

    @field_validator("output_formats", mode="after")
    @classmethod
    def _normalize_formats(cls, value: list[str]) -> list[str]:
        if not value:
            return []
        normalized = [item.lower().strip() for item in value if item]
        return [item for item in normalized if item]

    @model_validator(mode="after")
    def _validate_range(self) -> AccountListRequest:
        if self.start_time and self.end_time and self.start_time > self.end_time:
            raise ValueError("start_time must be before end_time")
        return self


class AccountListResult(BaseModel):
    """Response envelope for account extraction runs."""

    request_id: str
    generated_at: datetime
    indicators: list[FinancialIndicator]
    sources: list[SourceDocument] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    artifacts: dict[str, str] = Field(default_factory=dict)
