"""Tests for i4g.extraction.ner_rules — rule-based NER extraction."""

from __future__ import annotations

import warnings

from i4g.extraction.ner_rules import (
    extract_crypto_keywords,
    extract_entities,
    extract_names,
    extract_phone_numbers,
    extract_urls,
    extract_wallets,
)

# ---------------------------------------------------------------------------
# extract_wallets
# ---------------------------------------------------------------------------


class TestExtractWallets:
    def test_ethereum_address(self):
        text = "Pay to 0xAb5801a7D398351b8bE11C439e05C5B3259aeC9B"
        wallets = extract_wallets(text)
        assert any(w.startswith("0x") for w in wallets)

    def test_btc_bech32(self):
        text = "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"
        wallets = extract_wallets(text)
        assert len(wallets) >= 1

    def test_btc_legacy(self):
        text = "Send to 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
        wallets = extract_wallets(text)
        assert len(wallets) >= 1

    def test_no_wallets_in_plain_text(self):
        assert extract_wallets("Hello world") == []


# ---------------------------------------------------------------------------
# extract_urls
# ---------------------------------------------------------------------------


class TestExtractUrls:
    def test_http_url(self):
        text = "Visit https://example.com/scam"
        urls = extract_urls(text)
        assert any("example.com" in u for u in urls)

    def test_telegram_link(self):
        text = "Join us at t.me/fraud_group"
        urls = extract_urls(text)
        assert any("t.me" in u for u in urls)

    def test_whatsapp_link(self):
        text = "Contact wa.me/15551234567"
        urls = extract_urls(text)
        assert any("wa.me" in u for u in urls)

    def test_no_urls_in_plain_text(self):
        assert extract_urls("No links here") == []


# ---------------------------------------------------------------------------
# extract_phone_numbers
# ---------------------------------------------------------------------------


class TestExtractPhoneNumbers:
    def test_us_phone(self):
        text = "Call +1 555-123-4567"
        phones = extract_phone_numbers(text)
        assert len(phones) >= 1

    def test_no_phones_in_plain_text(self):
        assert extract_phone_numbers("Hello world") == []


# ---------------------------------------------------------------------------
# extract_names
# ---------------------------------------------------------------------------


class TestExtractNames:
    def test_capitalized_name(self):
        text = "John Doe sent the funds"
        names = extract_names(text)
        assert "John Doe" in names

    def test_multiple_names(self):
        text = "John Doe and Jane Smith"
        names = extract_names(text)
        assert "John Doe" in names
        assert "Jane Smith" in names

    def test_no_names_in_lowercase(self):
        assert extract_names("hello world") == []

    def test_banking_labels_not_extracted_as_names(self):
        text = "Bank Name: HSBC\nAccount Number: 12345678\nSort Code: 12-34-56"
        names = extract_names(text)
        assert "Bank Name" not in names
        assert "Account Number" not in names
        assert "Sort Code" not in names

    def test_scam_terms_not_extracted_as_names(self):
        text = "This is an Advance Fee scam involving a Money Mule"
        names = extract_names(text)
        assert "Advance Fee" not in names
        assert "Money Mule" not in names

    def test_financial_labels_not_extracted_as_names(self):
        text = "Routing Number: 021000021, Bank Address: 123 Main St, " "Account Name: Savings, Wire Transfer pending"
        names = extract_names(text)
        assert "Routing Number" not in names
        assert "Bank Address" not in names
        assert "Account Name" not in names
        assert "Wire Transfer" not in names

    def test_real_names_still_extracted_alongside_labels(self):
        text = "John Doe, Bank Name: HSBC, Account Number: 12345678, Jane Smith"
        names = extract_names(text)
        assert "John Doe" in names
        assert "Jane Smith" in names
        assert "Bank Name" not in names
        assert "Account Number" not in names


# ---------------------------------------------------------------------------
# extract_crypto_keywords
# ---------------------------------------------------------------------------


class TestExtractCryptoKeywords:
    def test_bitcoin_keyword(self):
        text = "Send via Bitcoin or Ethereum"
        keywords = extract_crypto_keywords(text)
        assert "bitcoin" in keywords
        assert "ethereum" in keywords

    def test_case_insensitive(self):
        text = "Invest in BTC and USDT"
        keywords = extract_crypto_keywords(text)
        assert "btc" in keywords
        assert "usdt" in keywords

    def test_no_keywords_in_plain_text(self):
        assert extract_crypto_keywords("Nothing crypto here") == []


# ---------------------------------------------------------------------------
# extract_entities (aggregate)
# ---------------------------------------------------------------------------


class TestExtractEntities:
    @staticmethod
    def _extract(text: str) -> dict:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            return extract_entities(text)

    def test_returns_all_keys(self):
        result = self._extract("Nothing here")
        expected_keys = {
            "wallet_addresses",
            "urls",
            "phone_numbers",
            "email_addresses",
            "bank_accounts",
            "social_handles",
            "people",
            "crypto_assets",
            "organizations",
            "locations",
            "scam_indicators",
        }
        assert set(result.keys()) == expected_keys

    def test_complex_text(self):
        text = (
            "John Doe sent bitcoin to 0xAb5801a7D398351b8bE11C439e05C5B3259aeC9B. "
            "Contact via https://scam.site or call +1 555-888-9999."
        )
        result = self._extract(text)
        assert len(result["wallet_addresses"]) >= 1
        assert len(result["urls"]) >= 1
        assert len(result["phone_numbers"]) >= 1
        assert len(result["people"]) >= 1
        assert len(result["crypto_assets"]) >= 1

    def test_urls_and_phones_in_separate_keys(self):
        text = "Visit https://example.com or call +1 555-000-1111"
        result = self._extract(text)
        assert any("example.com" in u for u in result["urls"])
        assert len(result["phone_numbers"]) >= 1
        # The old contact_channels key should not exist
        assert "contact_channels" not in result

    def test_emails_in_own_key(self):
        text = "Email alice@example.com for details"
        result = self._extract(text)
        assert any("alice@example.com" in e for e in result["email_addresses"])

    def test_bank_accounts_in_own_key(self):
        text = "Account number 12345678"
        result = self._extract(text)
        assert "12345678" in result["bank_accounts"]
