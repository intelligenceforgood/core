"""End-to-end smoke test: ingest a sample document with all PII types (F5).

This test constructs a realistic text block containing every PII category
that the regex pipeline must detect, feeds it through
``TokenizationService.tokenize_text_content()``, and verifies that every
PII value has been replaced by a token.

LLM detection is disabled (``enable_llm=False``) so the test runs offline.
"""

from unittest.mock import MagicMock

import pytest

from i4g.pii.observability import PiiVaultObservability
from i4g.pii.tokenization import TokenizationService
from i4g.store.pii_token_store import PiiTokenStore

SAMPLE_DOCUMENT = """\
CASE-ID: FRD twenty twenty five dash one two three four

Subject: John Doe
SSN: 123-45-6789
Date of Birth: 1985-03-22
Email: john.doe@example.com
Phone: +1 (555) 012-3456
Address: 456 Oak Avenue, Springfield

Financial Information:
  Credit Card: 4111 1111 1111 1111
  Bank routing: see attachment

Digital footprint:
  IP Address: 203.0.113.42
  Secondary IP: 198.51.100.7

Notes:
The subject contacted us from IP 10.0.0.1 recently.
Their SSN was also found as 123 45 6789 in a scanned document.
Alternative email: j.doe@corp.io
"""

# PII values that MUST be redacted (exact substrings)
EXPECTED_REDACTED = [
    "123-45-6789",
    "john.doe@example.com",
    "203.0.113.42",
    "198.51.100.7",
    "10.0.0.1",
    "4111 1111 1111 1111",
    "j.doe@corp.io",
]

# Token prefixes we expect to appear in the output
EXPECTED_PREFIXES = {"EID", "TIN", "IPA", "CCN"}


@pytest.fixture
def service():
    return TokenizationService(
        store=MagicMock(spec=PiiTokenStore),
        observability=MagicMock(spec=PiiVaultObservability),
        pepper="smoke-test-pepper",
        encryption_key="smoke-test-key!!" * 3,  # 48 chars
    )


class TestTokenizationSmoke:
    def test_all_pii_types_tokenized(self, service):
        result = service.tokenize_text_content(SAMPLE_DOCUMENT, enable_llm=False)

        for pii_value in EXPECTED_REDACTED:
            assert pii_value not in result, f"PII value '{pii_value}' was NOT redacted"

    def test_expected_token_prefixes_present(self, service):
        result = service.tokenize_text_content(SAMPLE_DOCUMENT, enable_llm=False)

        for prefix in EXPECTED_PREFIXES:
            assert f"{prefix}-" in result, f"Expected token prefix '{prefix}-' not found in output"

    def test_non_pii_text_preserved(self, service):
        result = service.tokenize_text_content(SAMPLE_DOCUMENT, enable_llm=False)

        # Key structural text should survive
        assert "CASE-ID: FRD twenty twenty five" in result
        assert "Subject:" in result
        assert "Financial Information:" in result
        assert "Digital footprint:" in result
        assert "Notes:" in result

    def test_multiple_passes_deterministic(self, service):
        r1 = service.tokenize_text_content(SAMPLE_DOCUMENT, enable_llm=False)
        r2 = service.tokenize_text_content(SAMPLE_DOCUMENT, enable_llm=False)
        assert r1 == r2, "Tokenization should be deterministic"
