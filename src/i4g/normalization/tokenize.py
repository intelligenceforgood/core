"""Lightweight tokenization helpers for normalization.

Provides safe, deterministic tokenization for small text snippets that feed
rule-based normalization. Designed to avoid heavy NLP deps and preserve
order while deduplicating.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Iterable, List

if TYPE_CHECKING:
    from i4g.pii.observability import PiiVaultObservability

# Simple pattern that keeps emails, URLs fragments, and alphanumerics together
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9@._'-]*")


def _dedupe_preserve_order(tokens: Iterable[str]) -> List[str]:
    """Return a list with duplicates removed while preserving first-seen order."""
    seen = set()
    ordered: List[str] = []
    for token in tokens:
        if token not in seen:
            seen.add(token)
            ordered.append(token)
    return ordered


def tokenize_text(
    text: str | None,
    min_len: int = 1,
    *,
    pii_observability: "PiiVaultObservability | None" = None,
    source: str = "text",
    detector: str | None = None,
    prefix: str | None = None,
    case_id: str | None = None,
) -> List[str]:
    """Tokenize a string into lowercase, deduplicated tokens.

    Args:
        text: Raw text to tokenize. Non-string inputs return an empty list.
        min_len: Minimum token length to keep after cleaning.

    Keyword Args:
        pii_observability: Optional metrics helper to record coverage.
        source: Label describing the input source (e.g., ``"text"`` or ``"ocr"``).
        detector: Detector name tied to the call site.
        prefix: PII prefix when known.
        case_id: Optional case identifier for audit trails.

    Returns:
        Ordered list of lowercase tokens with duplicates removed.
    """
    if not text or not isinstance(text, str):
        return []

    raw_tokens = _TOKEN_PATTERN.findall(text)
    cleaned = [t.lower().strip("'\"-._") for t in raw_tokens]
    filtered = [t for t in cleaned if len(t) >= min_len]
    tokens = _dedupe_preserve_order(filtered)

    if pii_observability:
        raw_bytes = len(text.encode("utf-8"))
        pii_observability.record_tokenization(
            token_count=len(tokens),
            field_count=1,
            raw_bytes=raw_bytes,
            source=source,
            detector=detector,
            prefix=prefix,
            case_id=case_id,
        )

    return tokens


def tokenize_fields(
    fields: Iterable[str],
    min_len: int = 1,
    *,
    pii_observability: "PiiVaultObservability | None" = None,
    source: str = "fields",
    detector: str | None = None,
    prefix: str | None = None,
    case_id: str | None = None,
) -> List[str]:
    """Tokenize multiple string fields into a single deduplicated token list.

    Args:
        fields: Iterable of string fields; non-string entries are skipped.
        min_len: Minimum token length to keep.

    Keyword Args:
        pii_observability: Optional metrics helper to record coverage.
        source: Label describing the input source (e.g., ``"text"`` or ``"ocr"``).
        detector: Detector name tied to the call site.
        prefix: PII prefix when known.
        case_id: Optional case identifier for audit trails.

    Returns:
        Ordered list of lowercase tokens aggregated across all fields.
    """
    tokens: List[str] = []
    raw_bytes = 0
    field_count = 0

    for field in fields:
        if not isinstance(field, str):
            continue
        field_count += 1
        raw_bytes += len(field.encode("utf-8"))
        tokens.extend(
            tokenize_text(
                field,
                min_len=min_len,
                pii_observability=None,
                source=source,
                detector=detector,
                prefix=prefix,
                case_id=case_id,
            )
        )

    deduped = _dedupe_preserve_order(tokens)

    if pii_observability and field_count:
        pii_observability.record_tokenization(
            token_count=len(deduped),
            field_count=field_count,
            raw_bytes=raw_bytes,
            source=source,
            detector=detector,
            prefix=prefix,
            case_id=case_id,
        )

    return deduped
