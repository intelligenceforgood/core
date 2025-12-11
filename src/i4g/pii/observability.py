"""Observability helpers focused on PII vault actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from i4g.observability import Observability, get_observability
from i4g.settings import Settings


@dataclass
class PiiVaultObservability:
    """Emit structured logs and metrics for tokenization and detokenization flows."""

    observability: Observability

    @classmethod
    def build(cls, *, component: str = "pii_vault", settings: Settings | None = None) -> "PiiVaultObservability":
        """Create a ``PiiVaultObservability`` wired to the shared Observability backend."""

        return cls(observability=get_observability(component=component, settings=settings))

    # ------------------------------------------------------------------
    # Tokenization coverage
    # ------------------------------------------------------------------

    def record_tokenization(
        self,
        *,
        token_count: int,
        field_count: int,
        raw_bytes: int | None,
        source: str,
        detector: str | None = None,
        prefix: str | None = None,
        case_id: str | None = None,
    ) -> None:
        """Record coverage for a tokenization run.

        Args:
            token_count: Number of tokens emitted.
            field_count: Number of fields analyzed.
            raw_bytes: Total bytes examined (if available).
            source: Source of data (e.g., ``"text"``, ``"ocr"``).
            detector: Detector or pipeline name that produced the tokens.
            prefix: PII prefix when known.
            case_id: Optional case identifier for audit trails.
        """

        tags = _clean_tags(
            {
                "source": source,
                "detector": detector,
                "prefix": prefix,
                "case_id": case_id,
            }
        )
        self.observability.increment("pii.tokenization.tokens", value=float(token_count), tags=tags)
        self.observability.increment("pii.tokenization.fields", value=float(field_count), tags=tags)
        if raw_bytes is not None:
            self.observability.increment("pii.tokenization.bytes", value=float(raw_bytes), tags=tags)
        self.observability.emit_event(
            "pii.tokenization.coverage",
            token_count=token_count,
            field_count=field_count,
            raw_bytes=raw_bytes,
            source=source,
            detector=detector,
            prefix=prefix,
            case_id=case_id,
        )

    def record_detector_confidence(
        self,
        *,
        detector: str,
        prefix: str,
        confidence: float,
        verdict: str,
        case_id: str | None = None,
    ) -> None:
        """Capture detector confidence buckets for tuning/alerting."""

        bucket = _confidence_bucket(confidence)
        tags = _clean_tags(
            {
                "detector": detector,
                "prefix": prefix,
                "bucket": bucket,
                "verdict": verdict,
                "case_id": case_id,
            }
        )
        self.observability.increment("pii.detector.confidence", value=1.0, tags=tags)
        self.observability.emit_event(
            "pii.detector.decision",
            detector=detector,
            prefix=prefix,
            confidence=confidence,
            bucket=bucket,
            verdict=verdict,
            case_id=case_id,
        )

    # ------------------------------------------------------------------
    # Detokenization access
    # ------------------------------------------------------------------

    def record_detokenization_attempt(
        self,
        *,
        actor: str,
        prefix: str | None,
        outcome: str,
        reason: str | None = None,
        case_id: str | None = None,
    ) -> None:
        """Log detokenization attempts and outcomes for audit trails."""

        tags = _clean_tags(
            {
                "actor": actor,
                "prefix": prefix,
                "outcome": outcome,
                "reason": reason,
                "case_id": case_id,
            }
        )
        self.observability.increment("pii.detokenization.attempt", value=1.0, tags=tags)
        self.observability.emit_event(
            "pii.detokenization.attempt",
            actor=actor,
            prefix=prefix,
            outcome=outcome,
            reason=reason,
            case_id=case_id,
        )

    def alert_unusual_access(
        self,
        *,
        actor: str,
        prefix: str | None,
        reason: str,
        severity: str = "warning",
        case_id: str | None = None,
    ) -> None:
        """Emit an alert-style log for unusual detokenization behavior."""

        tags = _clean_tags(
            {
                "actor": actor,
                "prefix": prefix,
                "severity": severity,
                "case_id": case_id,
            }
        )
        self.observability.increment("pii.detokenization.alert", value=1.0, tags=tags)
        self.observability.emit_event(
            "pii.detokenization.alert",
            actor=actor,
            prefix=prefix,
            reason=reason,
            severity=severity,
            case_id=case_id,
        )


def _confidence_bucket(confidence: float) -> str:
    if confidence < 0.4:
        return "very_low"
    if confidence < 0.6:
        return "low"
    if confidence < 0.8:
        return "medium"
    if confidence < 0.9:
        return "high"
    return "very_high"


def _clean_tags(tags: Mapping[str, str | None]) -> Mapping[str, str]:
    cleaned = {str(key): str(value) for key, value in tags.items() if value}
    return cleaned


__all__ = ["PiiVaultObservability"]
