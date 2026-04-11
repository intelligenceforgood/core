"""Regex-based extraction module.

Wraps the existing regex extractors from ``ner_rules.py`` behind the
``ModuleProtocol`` interface.  Each extractor emits ``ScoredEntity``
instances with ``source_module="regex"`` and high confidence for
pattern-matched types.
"""

from __future__ import annotations

from i4g.extraction.ner_rules import (
    extract_bank_accounts,
    extract_emails,
    extract_phone_numbers,
    extract_social_handles,
    extract_urls,
    extract_wallets,
)
from i4g.extraction.types import ScoredEntity
from i4g.utils.entity_types import normalize_entity_value

# ---------------------------------------------------------------------------
# Authority declarations — how much weight the regex module's opinion carries
# for each entity type in the merge engine.
# ---------------------------------------------------------------------------

_AUTHORITY: dict[str, float] = {
    "wallet_address": 1.0,
    "email_address": 1.0,
    "phone_number": 1.0,
    "url": 1.0,
    "bank_account": 0.9,
    "social_handle": 0.9,
}

_CONFIDENCE = 0.9
"""Default confidence for regex-matched entities."""


class RegexModule:
    """Rule-based extraction using compiled regex patterns.

    Covers high-precision technical entity types: wallets, emails, phones,
    URLs, bank accounts, and social handles.
    """

    @property
    def name(self) -> str:
        return "regex"

    @property
    def authority(self) -> dict[str, float]:
        return _AUTHORITY

    def extract(self, text: str) -> list[ScoredEntity]:
        """Run all regex extractors on *text*."""
        results: list[ScoredEntity] = []

        _extractors: list[tuple[str, list[str]]] = [
            ("wallet_address", extract_wallets(text)),
            ("url", extract_urls(text)),
            ("phone_number", extract_phone_numbers(text)),
            ("email_address", extract_emails(text)),
            ("bank_account", extract_bank_accounts(text)),
            ("social_handle", extract_social_handles(text)),
        ]

        for entity_type, values in _extractors:
            for raw in values:
                canonical = normalize_entity_value(entity_type, raw)
                results.append(
                    ScoredEntity(
                        entity_type=entity_type,
                        value=raw,
                        canonical_value=canonical,
                        confidence=_CONFIDENCE,
                        source_module=self.name,
                    )
                )

        return results
