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
)

# Social media / messaging handle pattern: @username anywhere in text
_SOCIAL_HANDLE_RE = re.compile(r"(?:^|\s)(@[A-Za-z]\w{2,})")

# URL patterns that also catch www. and bare domain names (domain.tld)
_WWW_RE = re.compile(r"\bwww\.[A-Za-z0-9][-A-Za-z0-9.]*\.[A-Za-z]{2,}\S*")
_BARE_DOMAIN_RE = re.compile(
    r"\b[A-Za-z0-9][-A-Za-z0-9]*\.(?:com|org|net|io|co|cc|vip|exchange|app|xyz|info|biz|me|site|online|live|pro|dev)\b"
    r"(?:/\S*)?"
)

# Bank account number heuristic: 6-17 digit sequences preceded by
# "account" keyword within ~40 chars.  Avoids matching dates,
# phone numbers, zip codes, and other numeric strings.
_ACCOUNT_CONTEXT_RE = re.compile(
    r"(?:account\s*(?:number|num|no|#)?[:\s]*)"  # keyword anchor
    r"(\d[\d\s-]{4,18}\d)",  # 6-17 digits with optional separators
    re.IGNORECASE,
)

# Terms that match the "Capitalized Two-Word" pattern but are NOT person names.
# Compared case-insensitively.  Keep sorted for readability.
_NON_PERSON_BLOCKLIST: frozenset[str] = frozenset(
    s.lower()
    for s in [
        # Banking / financial field labels
        "Account Name",
        "Account Number",
        "Account Type",
        "Bank Account",
        "Bank Address",
        "Bank Branch",
        "Bank Code",
        "Bank Details",
        "Bank Name",
        "Branch Code",
        "Branch Name",
        "Card Number",
        "Credit Card",
        "Debit Card",
        "Iban Number",
        "Loan Number",
        "Payment Method",
        "Payment Reference",
        "Pin Number",
        "Reference Number",
        "Routing Number",
        "Sort Code",
        "Swift Code",
        "Transaction Id",
        "Transfer Details",
        "Wire Transfer",
        # Scam / fraud terminology
        "Advance Fee",
        "Money Mule",
        "Money Order",
        "Money Transfer",
        "Gift Card",
        "Gift Cards",
        "Identity Theft",
        "Investment Scam",
        "Lottery Scam",
        "Phone Scam",
        "Prize Scam",
        "Romance Scam",
        "Tech Support",
        # Generic report / form labels
        "Case Number",
        "Case Status",
        "Contact Details",
        "Contact Information",
        "Email Address",
        "First Name",
        "Full Name",
        "Last Name",
        "Phone Number",
        "Postal Code",
        "Social Security",
        "Zip Code",
    ]
)


def extract_wallets(text: str) -> list[str]:
    """Find crypto wallet addresses (Ethereum, BTC, etc.)."""
    wallets = ETH_WALLET_RE.findall(text) + BTC_BECH32_RE.findall(text) + BTC_LEGACY_RE.findall(text)
    return list(set(wallets))


def extract_urls(text: str) -> list[str]:
    """Find URLs, www links, and bare domains. Telegram/WhatsApp links go to social handles."""
    urls: set[str] = set()
    # Full URLs (https?://)
    for u in URL_FULL_RE.findall(text):
        urls.add(u.rstrip(".,;)\"'"))
    # www. links
    for u in _WWW_RE.findall(text):
        urls.add(u.rstrip(".,;)\"'"))

    # Bare domain names — but skip email domains
    email_domains = {m.split("@")[1].lower() for m in EMAIL_RE.findall(text)}
    for u in _BARE_DOMAIN_RE.findall(text):
        cleaned = u.rstrip(".,;)\"'")
        # Skip if this domain is from an email address
        if cleaned.lower() in email_domains:
            continue
        # Skip if it's a substring of a URL already found
        if any(cleaned.lower() in existing.lower() for existing in urls):
            continue
        urls.add(cleaned)

    # t.me/ and wa.me/ links are treated as social handles, not URLs
    return sorted(urls)


def extract_social_handles(text: str) -> list[str]:
    """Find @handles for Telegram, Twitter, and other social platforms."""
    handles = set()
    for m in _SOCIAL_HANDLE_RE.finditer(text):
        handle = m.group(1)
        # Skip if it looks like an email (preceded by alphanumeric)
        start = m.start(1)
        if start > 0 and text[start - 1].isalnum():
            continue
        handles.add(handle)
    # Also extract from t.me/ links
    for m in TELEGRAM_RE.finditer(text):
        link = m.group()
        name = link.split("/")[-1]
        if name:
            handles.add("@" + name)
    return sorted(handles)


def extract_phone_numbers(text: str) -> list[str]:
    """Find phone numbers."""
    return list(set(PHONE_RE.findall(text)))


def extract_names(text: str) -> list[str]:
    """
    Very lightweight name extraction — not full NLP.
    Looks for capitalized 2-word sequences (e.g. John Doe), then filters out
    known non-person terms (banking labels, scam types, generic field headers).
    """
    candidates = re.findall(r"\b[A-Z][a-z]+\s[A-Z][a-z]+\b", text)
    return [c for c in candidates if c.lower() not in _NON_PERSON_BLOCKLIST]


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
        "urls": extract_urls(text),
        "phone_numbers": extract_phone_numbers(text),
        "email_addresses": extract_emails(text),
        "bank_accounts": extract_bank_accounts(text),
        "social_handles": extract_social_handles(text),
        "people": extract_names(text),
        "crypto_assets": extract_crypto_keywords(text),
        "organizations": [],
        "locations": [],
        "scam_indicators": [],
    }
