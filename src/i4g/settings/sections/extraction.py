"""Extraction pipeline settings."""

from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExtractionSettings(BaseSettings):
    """Configuration for the entity extraction pipeline.

    Controls which modules are enabled, confidence gating thresholds,
    authority weight overrides, and batch job throttling.
    """

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    enabled_modules: list[str] = Field(
        default=["regex", "llm"],
        validation_alias=AliasChoices("EXTRACTION_ENABLED_MODULES", "EXTRACTION__ENABLED_MODULES"),
    )
    """Modules to run during extraction. Options: regex, heuristic, llm, ml_ner."""

    llm_delay_seconds: float = Field(
        default=0.5,
        validation_alias=AliasChoices("EXTRACTION_LLM_DELAY_SECONDS", "EXTRACTION__LLM_DELAY_SECONDS"),
    )
    """Seconds to wait between LLM calls in batch mode (rate-limit guard)."""

    batch_concurrency: int = Field(
        default=1,
        validation_alias=AliasChoices("EXTRACTION_BATCH_CONCURRENCY", "EXTRACTION__BATCH_CONCURRENCY"),
    )
    """Number of cases to process concurrently in batch jobs."""

    # --------------------------------------------------------------------- #
    # Per-type confidence gates — entities below threshold are dropped.
    # --------------------------------------------------------------------- #

    gate_wallet_address: float = Field(
        default=0.5,
        validation_alias=AliasChoices("EXTRACTION_GATE_WALLET_ADDRESS", "EXTRACTION__GATE_WALLET_ADDRESS"),
    )
    gate_email_address: float = Field(
        default=0.5,
        validation_alias=AliasChoices("EXTRACTION_GATE_EMAIL_ADDRESS", "EXTRACTION__GATE_EMAIL_ADDRESS"),
    )
    gate_phone_number: float = Field(
        default=0.5,
        validation_alias=AliasChoices("EXTRACTION_GATE_PHONE_NUMBER", "EXTRACTION__GATE_PHONE_NUMBER"),
    )
    gate_url: float = Field(
        default=0.5,
        validation_alias=AliasChoices("EXTRACTION_GATE_URL", "EXTRACTION__GATE_URL"),
    )
    gate_bank_account: float = Field(
        default=0.5,
        validation_alias=AliasChoices("EXTRACTION_GATE_BANK_ACCOUNT", "EXTRACTION__GATE_BANK_ACCOUNT"),
    )
    gate_social_handle: float = Field(
        default=0.5,
        validation_alias=AliasChoices("EXTRACTION_GATE_SOCIAL_HANDLE", "EXTRACTION__GATE_SOCIAL_HANDLE"),
    )
    gate_person: float = Field(
        default=0.6,
        validation_alias=AliasChoices("EXTRACTION_GATE_PERSON", "EXTRACTION__GATE_PERSON"),
    )
    gate_organization: float = Field(
        default=0.6,
        validation_alias=AliasChoices("EXTRACTION_GATE_ORGANIZATION", "EXTRACTION__GATE_ORGANIZATION"),
    )
    gate_location: float = Field(
        default=0.5,
        validation_alias=AliasChoices("EXTRACTION_GATE_LOCATION", "EXTRACTION__GATE_LOCATION"),
    )
    gate_crypto_token: float = Field(
        default=0.4,
        validation_alias=AliasChoices("EXTRACTION_GATE_CRYPTO_TOKEN", "EXTRACTION__GATE_CRYPTO_TOKEN"),
    )
    gate_scam_indicator: float = Field(
        default=0.5,
        validation_alias=AliasChoices("EXTRACTION_GATE_SCAM_INDICATOR", "EXTRACTION__GATE_SCAM_INDICATOR"),
    )
    gate_domain: float = Field(
        default=0.5,
        validation_alias=AliasChoices("EXTRACTION_GATE_DOMAIN", "EXTRACTION__GATE_DOMAIN"),
    )

    def confidence_gates(self) -> dict[str, float]:
        """Return a ``{entity_type: threshold}`` mapping built from settings."""
        return {
            "wallet_address": self.gate_wallet_address,
            "email_address": self.gate_email_address,
            "phone_number": self.gate_phone_number,
            "url": self.gate_url,
            "bank_account": self.gate_bank_account,
            "social_handle": self.gate_social_handle,
            "person": self.gate_person,
            "organization": self.gate_organization,
            "location": self.gate_location,
            "crypto_token": self.gate_crypto_token,
            "scam_indicator": self.gate_scam_indicator,
            "domain": self.gate_domain,
        }
