"""ML NER extraction module.

Wraps the ML NER Vertex AI endpoint interaction behind the
``ModuleProtocol`` interface.  Passes through confidence scores
from the model (not hard-coded).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from i4g.extraction.types import ScoredEntity
from i4g.utils.entity_types import normalize_entity_type, normalize_entity_value

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Authority declarations — model confidence is passed through, authority
# determines its weight in the merge engine.
# ---------------------------------------------------------------------------

_AUTHORITY: dict[str, float] = {
    "person": 0.7,
    "organization": 0.7,
    "wallet_address": 0.6,
    "bank_account": 0.6,
    "phone_number": 0.6,
    "email_address": 0.6,
    "url": 0.6,
    "location": 0.7,
}

# Mapping from ML NER BIO tag types to canonical entity types.
_ML_TYPE_MAP: dict[str, str] = {
    "PERSON": "person",
    "PER": "person",
    "ORG": "organization",
    "CRYPTO_WALLET": "wallet_address",
    "BANK_ACCOUNT": "bank_account",
    "PHONE": "phone_number",
    "EMAIL": "email_address",
    "URL": "url",
    "LOC": "location",
    "LOCATION": "location",
}


class MLNERModule:
    """ML NER extraction module backed by a fine-tuned BERT model.

    The module calls the ML platform's entity extraction endpoint and
    converts the results into ``ScoredEntity`` instances with model
    confidence scores preserved.

    Args:
        predict_fn: A callable that takes ``(text, case_id)`` and returns
            a list of dicts with ``entity_type``, ``value``, ``confidence``,
            and optionally ``start``/``end`` span offsets.  If ``None``,
            the module is disabled and ``extract()`` returns an empty list.
    """

    def __init__(
        self,
        predict_fn: Any | None = None,
    ) -> None:
        self._predict = predict_fn

    @property
    def name(self) -> str:
        return "ml_ner"

    @property
    def authority(self) -> dict[str, float]:
        return _AUTHORITY

    def extract(self, text: str) -> list[ScoredEntity]:
        """Run ML NER on *text*.

        Returns:
            List of scored entities.  Empty if the module is disabled or
            the prediction fails.
        """
        if self._predict is None:
            return []

        try:
            predictions = self._predict(text)
        except Exception:
            logger.warning("ML NER prediction failed", exc_info=True)
            return []

        if not isinstance(predictions, list):
            return []

        results: list[ScoredEntity] = []
        for pred in predictions:
            if not isinstance(pred, dict):
                continue
            raw_type = pred.get("entity_type", "")
            entity_type = _ML_TYPE_MAP.get(raw_type, normalize_entity_type(raw_type))
            raw_value = str(pred.get("value", "")).strip()
            if not raw_value:
                continue
            confidence = float(pred.get("confidence", 0.5))
            canonical = normalize_entity_value(entity_type, raw_value)

            span = None
            if "start" in pred and "end" in pred:
                span = (int(pred["start"]), int(pred["end"]))

            results.append(
                ScoredEntity(
                    entity_type=entity_type,
                    value=raw_value,
                    canonical_value=canonical,
                    confidence=confidence,
                    source_module=self.name,
                    span=span,
                )
            )

        return results
