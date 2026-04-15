"""Entity normalization functions — canonical forms for types and values.

Moved from ``i4g.utils.entity_types`` during the v2 extraction refactor.
The original module re-exports everything for backward compatibility.
"""

from __future__ import annotations

import re

from i4g.utils.entity_types import (
    CANONICAL_ENTITY_TYPES,
    ENTITY_TYPE_LABELS,
    normalize_entity_type,
    normalize_entity_value,
)

__all__ = [
    "CANONICAL_ENTITY_TYPES",
    "ENTITY_TYPE_LABELS",
    "normalize_entity_type",
    "normalize_entity_value",
    "normalize_obfuscated_text",
]

# ---------------------------------------------------------------------------
# Domain-specific normalizers: handle obfuscated values
# ---------------------------------------------------------------------------

# Common obfuscation patterns used by scammers.
# Order matters — bracket/paren forms before word forms to avoid partial matches.
_OBFUSCATION_MAP: list[tuple[re.Pattern[str], str]] = [
    # Bracket / paren forms: [dot], [at], (dot), (at)
    (re.compile(r"\[dot\]", re.IGNORECASE), "."),
    (re.compile(r"\[at\]", re.IGNORECASE), "@"),
    (re.compile(r"\(dot\)", re.IGNORECASE), "."),
    (re.compile(r"\(at\)", re.IGNORECASE), "@"),
    # Word forms: " dot ", " at " (between word chars)
    (re.compile(r"(?<=\w)\s+dot\s+(?=\w)", re.IGNORECASE), "."),
    (re.compile(r"(?<=\w)\s+at\s+(?=\w)", re.IGNORECASE), "@"),
    # Dash-separated: " - dot - ", " -dot- "
    (re.compile(r"\s*-\s*dot\s*-\s*", re.IGNORECASE), "."),
    (re.compile(r"\s*-\s*at\s*-\s*", re.IGNORECASE), "@"),
]

# Leetspeak substitutions for common character replacements.
_LEET_MAP: dict[str, str] = {
    "0": "o",
    "1": "i",
    "3": "e",
    "4": "a",
    "5": "s",
    "7": "t",
    "8": "b",
    "@": "a",
    "$": "s",
}

_LEET_PATTERN = re.compile(r"[013457@$]")

# Known scam-domain keywords with common leetspeak variants.
# If a word matches one of these after leet-decode, keep the decoded form.
_LEET_KNOWN_WORDS: frozenset[str] = frozenset(
    {
        "google",
        "bitcoin",
        "coinbase",
        "binance",
        "metamask",
        "paypal",
        "cashapp",
        "zelle",
        "venmo",
        "blockchain",
        "ethereum",
        "tether",
        "support",
        "verify",
        "secure",
        "account",
        "wallet",
        "crypto",
        "transfer",
        "recovery",
        "helpdesk",
        "telegram",
    }
)

# Pattern to detect space-separated characters that may form a domain/email.
# e.g., "g o o g l e . c o m" → "google.com"
# Matches sequences of single characters (including . and @) separated by spaces.
_SPACED_CHARS_PATTERN = re.compile(r"(?<!\w)(?:[a-zA-Z0-9.@][ ]{1,3}){3,}[a-zA-Z0-9.@](?!\w)")


def _decode_leet(word: str) -> str:
    """Attempt to decode leetspeak substitutions in a single word.

    Only returns the decoded form if it matches a known scam keyword,
    to avoid false positives on legitimate numeric-plus-alpha strings.
    """
    if not _LEET_PATTERN.search(word):
        return word
    decoded = "".join(_LEET_MAP.get(ch, ch) for ch in word.lower())
    if decoded in _LEET_KNOWN_WORDS:
        return decoded
    return word


def _collapse_spaced_chars(text: str) -> str:
    """Collapse space-separated single characters into contiguous strings.

    ``"g o o g l e . c o m"`` → ``"google.com"``
    """

    def _collapse_match(m: re.Match[str]) -> str:
        segment = m.group(0)
        # Only collapse if tokens are single characters (including . and @)
        chars = segment.split()
        if all(len(c) == 1 for c in chars):
            return "".join(chars)
        return segment

    return _SPACED_CHARS_PATTERN.sub(_collapse_match, text)


def normalize_obfuscated_text(text: str) -> str:
    """Apply common de-obfuscation patterns to raw text.

    Handles three categories of scammer obfuscation:

    1. **Separator substitution**: ``"dot"`` → ``.``, ``"at"`` → ``@``,
       including bracket and paren variants.
    2. **Leetspeak**: ``"g00gle"`` → ``"google"`` (only for known keywords).
    3. **Spaced characters**: ``"g o o g l e . c o m"`` → ``"google.com"``.

    Args:
        text: Raw input text.

    Returns:
        Text with obfuscation patterns replaced.
    """
    if not text:
        return text or ""
    result = text

    # Phase 1: Collapse spaced characters first (before separator subs).
    result = _collapse_spaced_chars(result)

    # Phase 2: Replace separator-word patterns (dot, at, etc.).
    for pattern, replacement in _OBFUSCATION_MAP:
        result = pattern.sub(replacement, result)

    # Phase 3: Decode leetspeak in individual words.
    # Split on whitespace, but handle punctuation-attached tokens (e.g. "g00gle.com")
    # by splitting further on non-alphanumeric boundaries.
    tokens = result.split()
    decoded_tokens: list[str] = []
    for token in tokens:
        # Split token into (word, separator) segments to handle "g00gle.com"
        parts = re.split(r"([^a-zA-Z0-9]+)", token)
        decoded_parts = [_decode_leet(p) if p.isalnum() else p for p in parts]
        decoded_tokens.append("".join(decoded_parts))
    result = " ".join(decoded_tokens)

    return result
