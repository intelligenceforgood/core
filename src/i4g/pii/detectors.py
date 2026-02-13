"""Regex-based PII detection patterns.

Each detector returns a list of ``PiiMatch`` objects found in the input text.
The hybrid pipeline in ``tokenize_text_content`` runs regex detectors first,
then optionally invokes the LLM detector for contextual patterns that regex
cannot catch (e.g. "my social security number is nine one two ...").
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from i4g.patterns import (
    ADDRESS_RE,
    CC_RE,
    DOB_RE,
    EMAIL_RE,
    IPV4_RE,
    PHONE_RE,
    SSN_RE,
    luhn_check,
)


@dataclass(frozen=True, slots=True)
class PiiMatch:
    """A single PII occurrence found in text."""

    value: str
    prefix: str
    start: int
    end: int
    detector: str
    confidence: float = 1.0


# ---------------------------------------------------------------------------
# Public detector functions
# ---------------------------------------------------------------------------


def detect_emails(text: str) -> list[PiiMatch]:
    """Detect email addresses in text."""
    return [
        PiiMatch(value=m.group(), prefix="EID", start=m.start(), end=m.end(), detector="regex_email")
        for m in EMAIL_RE.finditer(text)
    ]


def detect_ipv4(text: str) -> list[PiiMatch]:
    """Detect IPv4 addresses in text."""
    return [
        PiiMatch(value=m.group(), prefix="IPA", start=m.start(), end=m.end(), detector="regex_ipv4")
        for m in IPV4_RE.finditer(text)
    ]


def detect_ssns(text: str) -> list[PiiMatch]:
    """Detect US Social Security Numbers (SSN) in text."""
    matches = []
    for m in SSN_RE.finditer(text):
        raw = m.group()
        digits = re.sub(r"[^\d]", "", raw)
        # SSN must be exactly 9 digits
        if len(digits) != 9:
            continue
        matches.append(
            PiiMatch(value=raw, prefix="TIN", start=m.start(), end=m.end(), detector="regex_ssn", confidence=0.9)
        )
    return matches


def detect_credit_cards(text: str) -> list[PiiMatch]:
    """Detect credit card numbers in text (Luhn-validated)."""
    matches = []
    for m in CC_RE.finditer(text):
        raw = m.group().strip()
        digits_only = re.sub(r"[^\d]", "", raw)
        if len(digits_only) < 13 or len(digits_only) > 19:
            continue
        if not luhn_check(digits_only):
            continue
        matches.append(
            PiiMatch(value=raw, prefix="CCN", start=m.start(), end=m.end(), detector="regex_cc", confidence=0.95)
        )
    return matches


def detect_phones(text: str) -> list[PiiMatch]:
    """Detect phone numbers in text.

    Requires at least 7 digits after stripping formatting characters to avoid
    false positives on short number sequences.
    """
    matches = []
    for m in PHONE_RE.finditer(text):
        raw = m.group()
        digits = re.sub(r"[^\d]", "", raw)
        # Require at least 7 digits to be considered a phone number
        if len(digits) < 7:
            continue
        # Avoid matching dates or SSNs (which have their own detectors)
        if SSN_RE.fullmatch(raw):
            continue
        matches.append(
            PiiMatch(value=raw, prefix="PHN", start=m.start(), end=m.end(), detector="regex_phone", confidence=0.85)
        )
    return matches


def detect_dobs(text: str) -> list[PiiMatch]:
    """Detect date-of-birth patterns in text."""
    return [
        PiiMatch(value=m.group(), prefix="DOB", start=m.start(), end=m.end(), detector="regex_dob", confidence=0.7)
        for m in DOB_RE.finditer(text)
    ]


def detect_addresses(text: str) -> list[PiiMatch]:
    """Detect US street addresses in text (heuristic)."""
    return [
        PiiMatch(
            value=m.group().strip(),
            prefix="ADR",
            start=m.start(),
            end=m.end(),
            detector="regex_address",
            confidence=0.75,
        )
        for m in ADDRESS_RE.finditer(text)
    ]


# ---------------------------------------------------------------------------
# Ordered detector pipeline
# ---------------------------------------------------------------------------

# Detection order: more specific patterns first to avoid overlap.
# Email and IP can't conflict.  SSN before phone (SSNs are 9-digit sequences
# that could also match the phone pattern).  Credit card before phone for the
# same reason.
ALL_DETECTORS: list[tuple[str, callable]] = [
    ("email", detect_emails),
    ("ipv4", detect_ipv4),
    ("ssn", detect_ssns),
    ("credit_card", detect_credit_cards),
    ("dob", detect_dobs),
    ("address", detect_addresses),
    ("phone", detect_phones),
]


def detect_all(text: str) -> list[PiiMatch]:
    """Run all regex detectors and return non-overlapping matches.

    Matches from earlier (higher-priority) detectors take precedence when
    spans overlap.
    """
    occupied: list[tuple[int, int]] = []
    results: list[PiiMatch] = []

    for _name, detector_fn in ALL_DETECTORS:
        for match in detector_fn(text):
            # Check for overlap with already-claimed spans
            if any(match.start < occ_end and match.end > occ_start for occ_start, occ_end in occupied):
                continue
            occupied.append((match.start, match.end))
            results.append(match)

    # Sort by position so replacement can proceed right-to-left
    results.sort(key=lambda m: m.start)
    return results


__all__ = [
    "PiiMatch",
    "detect_all",
    "detect_emails",
    "detect_ipv4",
    "detect_ssns",
    "detect_credit_cards",
    "detect_phones",
    "detect_dobs",
    "detect_addresses",
]
