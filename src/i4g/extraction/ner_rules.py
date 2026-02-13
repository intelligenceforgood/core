"""
Rule-based Named Entity Extraction for scam-related content.

This uses simple regex and keyword heuristics to identify
useful entities (wallet addresses, URLs, crypto terms, etc.).
"""

import re

from i4g.patterns import (
    BTC_BECH32_RE,
    BTC_LEGACY_RE,
    ETH_WALLET_RE,
    PHONE_RE,
    TELEGRAM_RE,
    URL_FULL_RE,
    WHATSAPP_RE,
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


def extract_entities(text: str) -> dict[str, list[str]]:
    """
    Aggregate all extraction results into a single dictionary.
    """
    return {
        "wallet_addresses": extract_wallets(text),
        "urls": extract_urls(text),
        "phone_numbers": extract_phone_numbers(text),
        "names": extract_names(text),
        "crypto_keywords": extract_crypto_keywords(text),
    }
