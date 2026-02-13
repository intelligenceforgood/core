import pytest
from unittest.mock import MagicMock, patch
from i4g.pii.tokenization import TokenizationService, TokenizedValue
from i4g.store.pii_token_store import PiiTokenStore
from i4g.pii.observability import PiiVaultObservability

@pytest.fixture
def mock_store():
    return MagicMock(spec=PiiTokenStore)

@pytest.fixture
def mock_observability():
    return MagicMock(spec=PiiVaultObservability)

@pytest.fixture
def service(mock_store, mock_observability):
    return TokenizationService(
        store=mock_store,
        observability=mock_observability,
        pepper="test-pepper",
        encryption_key="test-key" * 6 # 48 chars, base64 compatible length
    )

def test_tokenize_email(service, mock_store):
    # EID normalization: lowercase
    result = service.tokenize("Test@Example.COM", "EID")
    
    assert result.prefix == "EID"
    assert result.normalized_value == "test@example.com"
    assert result.token.startswith("EID-")
    assert len(result.token) == 12 # 3 + 1 + 8
    
    mock_store.upsert_token.assert_called_once()
    call_args = mock_store.upsert_token.call_args[1]
    assert call_args["token"] == result.token
    assert call_args["normalized_value"] == "test@example.com"
    assert call_args["canonical_value"] == "Test@Example.COM"

def test_tokenize_determinism(service):
    # Same input should produce same token
    res1 = service.tokenize("test@example.com", "EID")
    res2 = service.tokenize("test@example.com", "EID")
    
    assert res1.token == res2.token
    assert res1.digest == res2.digest

def test_tokenize_different_inputs(service):
    res1 = service.tokenize("test1@example.com", "EID")
    res2 = service.tokenize("test2@example.com", "EID")
    
    assert res1.token != res2.token

def test_tokenize_entities(service):
    entities = {
        "email": ["a@b.com", "c@d.com"],
        "phone": ["+1234567890"]
    }
    
    result = service.tokenize_entities(entities)
    
    assert "email" in result
    assert len(result["email"]) == 2
    assert result["email"][0]["prefix"] == "EID"
    
    assert "phone" in result
    assert len(result["phone"]) == 1
    assert result["phone"][0]["prefix"] == "PHN"

def test_tokenize_tree(service):
    data = {
        "email": "test@example.com",
        "nested": {
            "phone": "+1234567890",
            "safe": "value"
        },
        "list": [
            {"ip_address": "1.2.3.4"},
            "not-pii"
        ]
    }
    
    result = service.tokenize_tree(data)
    
    assert result["email"].startswith("EID-")
    assert result["nested"]["phone"].startswith("PHN-")
    assert result["nested"]["safe"] == "value"
    assert result["list"][0]["ip_address"].startswith("IPA-")
    assert result["list"][1] == "not-pii"

def test_tokenize_text_content_email_and_ip(service):
    """Original test: email + IPv4 detection still works."""
    text = "Contact me at test@example.com or 192.168.1.1 for info."
    
    result = service.tokenize_text_content(text, enable_llm=False)
    
    assert "test@example.com" not in result
    assert "192.168.1.1" not in result
    assert "EID-" in result
    assert "IPA-" in result
    assert "Contact me at " in result


def test_tokenize_text_content_ssn(service):
    """F1: SSN detection in free text."""
    text = "My SSN is 123-45-6789 and that's private."
    result = service.tokenize_text_content(text, enable_llm=False)

    assert "123-45-6789" not in result
    assert "TIN-" in result


def test_tokenize_text_content_credit_card(service):
    """F1: Credit card detection (Luhn-valid number)."""
    text = "Charge card 4111 1111 1111 1111 please."
    result = service.tokenize_text_content(text, enable_llm=False)

    assert "4111 1111 1111 1111" not in result
    assert "CCN-" in result


def test_tokenize_text_content_dob(service):
    """F1: Date of birth detection."""
    text = "Born on 1990-05-15. Happy birthday!"
    result = service.tokenize_text_content(text, enable_llm=False)

    assert "1990-05-15" not in result
    assert "DOB-" in result


def test_tokenize_text_content_phone(service):
    """F1: Phone number detection."""
    text = "Call me at (555) 012-3456 anytime."
    result = service.tokenize_text_content(text, enable_llm=False)

    assert "(555) 012-3456" not in result
    assert "PHN-" in result


def test_tokenize_text_content_address(service):
    """F6: Street address detection."""
    text = "I live at 123 Main Street in Springfield."
    result = service.tokenize_text_content(text, enable_llm=False)

    assert "123 Main Street" not in result
    assert "ADR-" in result


def test_tokenize_text_content_mixed(service):
    """Multiple PII types in a single text."""
    text = (
        "Name: John Doe, SSN: 123-45-6789, "
        "Email: john@example.com, "
        "IP: 10.0.0.1, "
        "Card: 4111 1111 1111 1111"
    )
    result = service.tokenize_text_content(text, enable_llm=False)

    assert "123-45-6789" not in result
    assert "john@example.com" not in result
    assert "10.0.0.1" not in result
    assert "4111 1111 1111 1111" not in result


def test_tokenize_text_content_empty(service):
    """Empty text returns empty string."""
    assert service.tokenize_text_content("", enable_llm=False) == ""
    assert service.tokenize_text_content(None, enable_llm=False) is None


def test_tokenize_text_content_no_pii(service):
    """Text without PII is returned unchanged."""
    text = "This is a normal sentence without any sensitive data."
    result = service.tokenize_text_content(text, enable_llm=False)
    assert result == text


def test_detokenize(service, mock_store):
    mock_token_record = MagicMock()
    mock_token_record.canonical_value = "original-value"
    mock_store.fetch.return_value = mock_token_record
    
    result = service.detokenize("EID-12345678")
    
    assert result == mock_token_record
    mock_store.fetch.assert_called_with("EID-12345678")

def test_is_token():
    assert TokenizationService.is_token("EID-1A2B3C4D")
    assert not TokenizationService.is_token("invalid")
    assert not TokenizationService.is_token("EID-123") # Too short


# ---------------------------------------------------------------------------
# F7: Prefix catalog coverage
# ---------------------------------------------------------------------------


class TestPrefixCatalog:
    """Verify the entity-prefix map covers all active TDD prefixes."""

    EXPECTED_PREFIXES = {
        "EID", "PHN", "IPA", "ASN", "BAN", "WLT", "DOC", "BFP", "NAM", "ADR",
        "DOB", "TIN", "PID", "SID", "EMP", "GOV", "CCN", "IBN", "RTN", "SWF",
        "ACH", "BTC", "ETH", "MAC", "DID", "CID", "HID", "MRN", "VIN", "LPL",
        "LOC", "PLC",
    }

    def test_entity_prefix_map_coverage(self):
        mapped_prefixes = set(TokenizationService._ENTITY_PREFIX_MAP.values())
        missing = self.EXPECTED_PREFIXES - mapped_prefixes
        assert not missing, f"Missing prefixes in _ENTITY_PREFIX_MAP: {missing}"

    def test_infer_prefix_variations(self):
        svc = TokenizationService.__new__(TokenizationService)
        # Verify key-name heuristics work for common field names
        cases = {
            "email_address": "EID",
            "phone_number": "PHN",
            "mobile": "PHN",
            "ip_address": "IPA",
            "ssn": "TIN",
            "social_security": "TIN",
            "credit_card": "CCN",
            "card_number": "CCN",
            "home_address": "ADR",
            "street_address": "ADR",
            "date_of_birth": "DOB",
            "passport": "PID",
            "drivers_license": "SID",
            "license_plate": "LPL",
            "mac_address": "MAC",
            "iban": "IBN",
            "routing_number": "RTN",
        }
        for key, expected_prefix in cases.items():
            result = svc._infer_prefix(key)
            assert result == expected_prefix, f"_infer_prefix('{key}') = '{result}', expected '{expected_prefix}'"
