"""Tests for i4g.extraction.ner_rules — rule-based NER extraction."""

from __future__ import annotations

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
    def test_returns_all_keys(self):
        result = extract_entities("Nothing here")
        expected_keys = {
            "wallet_addresses",
            "contact_channels",
            "email_address",
            "bank_account",
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
        result = extract_entities(text)
        assert len(result["wallet_addresses"]) >= 1
        assert len(result["contact_channels"]) >= 1
        assert len(result["people"]) >= 1
        assert len(result["crypto_assets"]) >= 1
