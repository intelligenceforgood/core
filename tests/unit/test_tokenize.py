"""Unit tests for i4g.normalization.tokenize."""

from i4g.normalization.tokenize import tokenize_fields, tokenize_text


def test_tokenize_text_basic_and_dedupes():
    text = "Binance Exchange, Trust Wallet! Binance"
    assert tokenize_text(text) == ["binance", "exchange", "trust", "wallet"]


def test_tokenize_text_preserves_email_like_tokens():
    text = "Contact us at support@example.com or visit example.com/contact"
    tokens = tokenize_text(text)
    assert "support@example.com" in tokens
    assert "example.com" in tokens


def test_tokenize_text_respects_min_len_and_non_str_inputs():
    assert tokenize_text("A b cd", min_len=2) == ["cd"]
    assert tokenize_text(None) == []
    assert tokenize_text(123) == []


def test_tokenize_fields_combines_and_dedupes():
    fields = ["Trust Wallet", "Wallet address", "trust@example.com"]
    tokens = tokenize_fields(fields)
    assert tokens == ["trust", "wallet", "address", "trust@example.com"]


def test_tokenize_text_records_observability():
    class StubObservability:
        def __init__(self) -> None:
            self.calls = []

        def record_tokenization(self, **kwargs):
            self.calls.append(kwargs)

    observer = StubObservability()
    tokens = tokenize_text("Tokenization check", pii_observability=observer, detector="unit")

    assert tokens == ["tokenization", "check"]
    assert observer.calls
    recorded = observer.calls[0]
    assert recorded["token_count"] == 2
    assert recorded["field_count"] == 1
    assert recorded["detector"] == "unit"
