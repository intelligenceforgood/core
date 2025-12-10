"""Lightweight tokenization helpers for normalization.

Provides safe, deterministic tokenization for small text snippets that feed
rule-based normalization. Designed to avoid heavy NLP deps and preserve
order while deduplicating.
"""

from __future__ import annotations

import re
from typing import Iterable, List

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


def tokenize_text(text: str | None, min_len: int = 1) -> List[str]:
    """Tokenize a string into lowercase, deduplicated tokens.

    Args:
        text: Raw text to tokenize. Non-string inputs return an empty list.
        min_len: Minimum token length to keep after cleaning.

    Returns:
        Ordered list of lowercase tokens with duplicates removed.
    """
    if not text or not isinstance(text, str):
        return []

    raw_tokens = _TOKEN_PATTERN.findall(text)
    cleaned = [t.lower().strip("'\"-._") for t in raw_tokens]
    filtered = [t for t in cleaned if len(t) >= min_len]
    return _dedupe_preserve_order(filtered)


def tokenize_fields(fields: Iterable[str], min_len: int = 1) -> List[str]:
    """Tokenize multiple string fields into a single deduplicated token list.

    Args:
        fields: Iterable of string fields; non-string entries are skipped.
        min_len: Minimum token length to keep.

    Returns:
        Ordered list of lowercase tokens aggregated across all fields.
    """
    tokens: List[str] = []
    for field in fields:
        tokens.extend(tokenize_text(field, min_len=min_len))
    return _dedupe_preserve_order(tokens)
