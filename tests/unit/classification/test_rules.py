"""Tests for i4g.classification.rules — regex-based signal detection."""

from __future__ import annotations

import pytest

from i4g.classification.rules import (
    BTC_PATTERN,
    EMAIL_PATTERN,
    ETH_PATTERN,
    PHONE_PATTERN,
    URL_PATTERN,
    detect_signals,
)


# ---------------------------------------------------------------------------
# Pattern-level unit tests
# ---------------------------------------------------------------------------


class TestBTCPattern:
    def test_legacy_address(self):
        text = "Send to 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
        import re

        assert re.search(BTC_PATTERN, text) is not None

    def test_segwit_address(self):
        text = "Address 3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"
        import re

        assert re.search(BTC_PATTERN, text) is not None

    def test_bech32_address(self):
        text = "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"
        import re

        assert re.search(BTC_PATTERN, text) is not None


class TestETHPattern:
    def test_valid_eth_address(self):
        text = "Send ETH to 0xAb5801a7D398351b8bE11C439e05C5B3259aeC9B"
        import re

        assert re.search(ETH_PATTERN, text) is not None

    def test_short_hex_not_matched(self):
        text = "Not an address: 0xAb5801"
        import re

        assert re.search(ETH_PATTERN, text) is None


# ---------------------------------------------------------------------------
# detect_signals integration tests
# ---------------------------------------------------------------------------


class TestDetectSignals:
    def test_empty_text_returns_no_signals(self):
        result = detect_signals("")
        assert result == {"actions": [], "channel": []}

    def test_crypto_wallet_detected(self):
        text = "Send BTC to 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
        result = detect_signals(text)
        assert len(result["actions"]) == 1
        assert result["actions"][0].label == "ACTION.CRYPTO"
        assert result["actions"][0].confidence == 1.0

    def test_eth_wallet_detected(self):
        text = "Transfer to 0xAb5801a7D398351b8bE11C439e05C5B3259aeC9B"
        result = detect_signals(text)
        labels = [s.label for s in result["actions"]]
        assert "ACTION.CRYPTO" in labels

    def test_url_detected(self):
        text = "Click here: https://example.com/phish"
        result = detect_signals(text)
        labels = [s.label for s in result["actions"]]
        assert "ACTION.CLICK_LINK" in labels

    def test_phone_number_detected(self):
        text = "Call me at (555) 123-4567"
        result = detect_signals(text)
        labels = [s.label for s in result["channel"]]
        assert "CHANNEL.PHONE" in labels

    def test_email_detected(self):
        text = "Contact admin@scamsite.org for payment"
        result = detect_signals(text)
        labels = [s.label for s in result["channel"]]
        assert "CHANNEL.EMAIL" in labels

    def test_multiple_signals(self):
        text = (
            "Send bitcoin to 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa "
            "or visit https://scam.com and email scam@evil.com"
        )
        result = detect_signals(text)
        action_labels = {s.label for s in result["actions"]}
        channel_labels = {s.label for s in result["channel"]}
        assert "ACTION.CRYPTO" in action_labels
        assert "ACTION.CLICK_LINK" in action_labels
        assert "CHANNEL.EMAIL" in channel_labels

    def test_no_false_positives_on_plain_text(self):
        text = "Today was a sunny day and nothing bad happened."
        result = detect_signals(text)
        assert result["actions"] == []
        assert result["channel"] == []

    def test_scored_label_has_explanation(self):
        text = "0xAb5801a7D398351b8bE11C439e05C5B3259aeC9B"
        result = detect_signals(text)
        for scored in result["actions"]:
            assert scored.explanation is not None
            assert len(scored.explanation) > 0
