"""
Rule-based Named Entity Extraction for scam-related content.

This uses simple regex and keyword heuristics to identify
useful entities (wallet addresses, URLs, crypto terms, etc.).
"""

import re

from i4g.patterns import (
    BTC_BECH32_RE,
    BTC_LEGACY_RE,
    EMAIL_RE,
    ETH_WALLET_RE,
    PHONE_RE,
    TELEGRAM_RE,
    URL_FULL_RE,
    WHATSAPP_RE,
)

# Bank account number heuristic: 6-17 digit sequences preceded by
# "account" keyword within ~40 chars.  Avoids matching dates,
# phone numbers, zip codes, and other numeric strings.
_ACCOUNT_CONTEXT_RE = re.compile(
    r"(?:account\s*(?:number|num|no|#)?[:\s]*)"  # keyword anchor
    r"(\d[\d\s-]{4,18}\d)",  # 6-17 digits with optional separators
    re.IGNORECASE,
)


def extract_wallets(text: str) -> list[str]:
    """Find crypto wallet addresses (Ethereum, BTC, etc.)."""
    wallets = ETH_WALLET_RE.findall(text) + BTC_BECH32_RE.findall(text) + BTC_LEGACY_RE.findall(text)
    return list(set(wallets))


def extract_urls(text: str) -> list[str]:
    """Find URLs or Telegram/WhatsApp links."""
    urls = URL_FULL_RE.findall(text)
    tgram = TELEGRAM_RE.findall(text)
    wa = WHATSAPP_RE.findall(text)
    return list(set(urls + tgram + wa))


def extract_phone_numbers(text: str) -> list[str]:
    """Find phone numbers."""
    return list(set(PHONE_RE.findall(text)))


def extract_names(text: str) -> list[str]:
    """
    Very lightweight name extraction — not full NLP.
    Looks for capitalized 2-word sequences (e.g. John Doe).
    """
    return re.findall(r"\b[A-Z][a-z]+\s[A-Z][a-z]+\b", text)


def extract_crypto_keywords(text: str) -> list[str]:
    """Detect crypto-related terms."""
    keywords = [
        "bitcoin",
        "btc",
        "eth",
        "ethereum",
        "usdt",
        "bnb",
        "wallet",
        "metamask",
    ]
    found = [kw for kw in keywords if kw.lower() in text.lower()]
    return list(set(found))


def extract_emails(text: str) -> list[str]:
    """Find email addresses."""
    return list(set(EMAIL_RE.findall(text)))


def extract_bank_accounts(text: str) -> list[str]:
    """Find bank/financial account numbers near contextual keywords."""
    matches = _ACCOUNT_CONTEXT_RE.findall(text)
    # Normalize: strip whitespace/dashes, keep only digit strings >=6 digits
    results: list[str] = []
    for m in matches:
        digits = re.sub(r"[\s-]", "", m)
        if 6 <= len(digits) <= 17:
            results.append(digits)
    return list(set(results))


def extract_entities(text: str) -> dict[str, list[str]]:
    """
    Aggregate all extraction results into a single dictionary.

    Keys are aligned with ``_ENTITY_KEYS`` used by the entity extraction job
    so that merge works without a mapping layer.
    """
    return {
        "wallet_addresses": extract_wallets(text),
        "contact_channels": extract_urls(text) + extract_phone_numbers(text),
        "email_address": extract_emails(text),
        "bank_account": extract_bank_accounts(text),
        "people": extract_names(text),
        "crypto_assets": extract_crypto_keywords(text),
        "organizations": [],
        "locations": [],
        "scam_indicators": [],
    }
