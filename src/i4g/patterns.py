"""Canonical regex patterns shared across extraction, classification, and PII modules.

Every regex that appears in more than one module should live here so that
pattern updates are applied in a single place.  Consumers import compiled
``re.Pattern`` objects (or the ``luhn_check`` utility) and apply their
own match-level post-processing (e.g. digit-count guards, Luhn validation).
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

# ---------------------------------------------------------------------------
# Phone numbers — international + North American formats
# ---------------------------------------------------------------------------

PHONE_RE = re.compile(
    r"(?:\+\d{1,3}[\s.-]?)?"  # optional country code
    r"(?:\(?\d{2,4}\)?[\s.-]?)?"  # optional area code
    r"\d{3,4}[\s.-]?\d{3,4}"  # subscriber number
    r"\b"
)

# ---------------------------------------------------------------------------
# Cryptocurrency wallet addresses
# ---------------------------------------------------------------------------

ETH_WALLET_RE = re.compile(r"\b0x[a-fA-F0-9]{40}\b")
BTC_BECH32_RE = re.compile(r"\bbc1[a-zA-HJ-NP-Z0-9]{25,39}\b")
BTC_LEGACY_RE = re.compile(r"\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b")

# Combined BTC pattern (bech32 + legacy) for single-pass detection.
BTC_ALL_RE = re.compile(r"\b(?:bc1|[13])[a-zA-HJ-NP-Z0-9]{25,39}\b")

# ---------------------------------------------------------------------------
# URLs & messaging links
# ---------------------------------------------------------------------------

URL_RE = re.compile(r"https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+")
"""Strict URL pattern — matches scheme + authority; stops at path separators."""

URL_FULL_RE = re.compile(r"https?://\S+")
"""Broad URL pattern — matches everything after the scheme up to whitespace."""

TELEGRAM_RE = re.compile(r"t\.me/[A-Za-z0-9_]+")
WHATSAPP_RE = re.compile(r"wa\.me/\d+")

# ---------------------------------------------------------------------------
# PII-specific patterns
# ---------------------------------------------------------------------------

# US SSN: 3-2-4 digits with separators.  Rejects known-invalid area numbers.
SSN_RE = re.compile(r"\b(?!000|666|9\d{2})\d{3}[- ]?\d{2}[- ]?\d{4}\b")

# Credit-card numbers: 13–19 digits, optional groups of 4 with separators
CC_RE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")

# Date of birth: common date formats (MM/DD/YYYY, DD-MM-YYYY, YYYY-MM-DD, etc.)
DOB_RE = re.compile(
    r"\b(?:"
    # YYYY-MM-DD
    r"(?:19|20)\d{2}[/-](?:0[1-9]|1[0-2])[/-](?:0[1-9]|[12]\d|3[01])" r"|"
    # MM/DD/YYYY or DD/MM/YYYY
    r"(?:0[1-9]|1[0-2])[/-](?:0[1-9]|[12]\d|3[01])[/-](?:19|20)\d{2}" r"|"
    # DD-Mon-YYYY (e.g. 15-Jan-1990)
    r"(?:0[1-9]|[12]\d|3[01])[- ](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[- ](?:19|20)\d{2}" r")\b",
    re.IGNORECASE,
)

# IPv4
IPV4_RE = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b")

# US street address (simplified heuristic — number + street name + suffix)
ADDRESS_RE = re.compile(
    r"\b\d{1,6}\s+"  # street number
    r"(?:[A-Z][a-z]+\.?\s+){1,4}"  # street name words
    r"(?:St(?:reet)?|Ave(?:nue)?|Blvd|Boulevard|Dr(?:ive)?|"
    r"Rd|Road|Ln|Lane|Ct|Court|Pl|Place|Way|Cir(?:cle)?|"
    r"Pkwy|Parkway|Hwy|Highway|Ter(?:race)?|Loop)"
    r"\.?"
    r"(?:\s*(?:#|Apt|Suite|Ste|Unit|Bldg)\s*\S+)?",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def luhn_check(number: str) -> bool:
    """Validate a number string with the Luhn algorithm (credit-card checksum)."""
    digits = [int(d) for d in number if d.isdigit()]
    if len(digits) < 13:
        return False
    checksum = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0
