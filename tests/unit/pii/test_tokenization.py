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

def test_tokenize_text_content(service):
    text = "Contact me at test@example.com or 192.168.1.1 for info."
    
    result = service.tokenize_text_content(text)
    
    assert "test@example.com" not in result
    assert "192.168.1.1" not in result
    assert "EID-" in result
    assert "IPA-" in result
    assert "Contact me at " in result

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
