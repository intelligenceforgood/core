"""Heuristic-based extraction module.

Wraps the lightweight name extraction and crypto keyword detection from
``ner_rules.py`` behind the ``ModuleProtocol`` interface.  These are
deliberately low-authority because the heuristics are noisy.
"""

from __future__ import annotations

from i4g.extraction.ner_rules import extract_crypto_keywords, extract_names
from i4g.extraction.types import ScoredEntity
from i4g.utils.entity_types import normalize_entity_value

# ---------------------------------------------------------------------------
# Authority declarations — deliberately low for heuristic extractors.
# ---------------------------------------------------------------------------

_AUTHORITY: dict[str, float] = {
    "person": 0.4,
    "crypto_token": 0.4,
}

_PERSON_CONFIDENCE = 0.5
_CRYPTO_CONFIDENCE = 0.5


class HeuristicModule:
    """Lightweight heuristic extraction for names and crypto keywords.

    Uses capitalized two-word pattern matching for person names and keyword
    lookup for crypto tokens.  Both are low-precision and should be
    corroborated by other modules.
    """

    @property
    def name(self) -> str:
        return "heuristic"

    @property
    def authority(self) -> dict[str, float]:
        return _AUTHORITY

    def extract(self, text: str) -> list[ScoredEntity]:
        """Run heuristic extractors on *text*."""
        results: list[ScoredEntity] = []

        for raw in extract_names(text):
            canonical = normalize_entity_value("person", raw)
            results.append(
                ScoredEntity(
                    entity_type="person",
                    value=raw,
                    canonical_value=canonical,
                    confidence=_PERSON_CONFIDENCE,
                    source_module=self.name,
                )
            )

        for raw in extract_crypto_keywords(text):
            canonical = normalize_entity_value("crypto_token", raw)
            results.append(
                ScoredEntity(
                    entity_type="crypto_token",
                    value=raw,
                    canonical_value=canonical,
                    confidence=_CRYPTO_CONFIDENCE,
                    source_module=self.name,
                )
            )

        return results
