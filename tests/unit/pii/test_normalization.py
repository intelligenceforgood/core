import pytest
from i4g.pii.normalization import normalize, NormalizationError

def test_normalize_email():
    assert normalize("EID", "Test@Example.COM") == "test@example.com"
    assert normalize("EID", "  user@domain.org  ") == "user@domain.org"
    
    with pytest.raises(NormalizationError):
        normalize("EID", "invalid-email")
        
    with pytest.raises(NormalizationError):
        normalize("EID", "")


def test_normalize_email_idn():
    """F4: Punycode/IDN handling for international domain names."""
    # ASCII domain passes through unchanged
    assert normalize("EID", "user@example.com") == "user@example.com"

    # IDN domain gets encoded to ACE (Punycode)
    result = normalize("EID", "user@münchen.de")
    assert result == "user@xn--mnchen-3ya.de"


def test_normalize_phone():
    # Basic stripping still works
    result = normalize("PHN", "+1-555-0100")
    # With phonenumbers installed, should be E.164
    assert result.startswith("+") or result.isdigit()
    
    with pytest.raises(NormalizationError):
        normalize("PHN", "")


def test_normalize_phone_e164():
    """F2: Phone normalization with python-phonenumbers."""
    try:
        import phonenumbers
        # US number should normalize to E.164
        result = normalize("PHN", "(202) 555-0173")
        assert result.startswith("+1")
        assert result == "+12025550173"
    except ImportError:
        pytest.skip("python-phonenumbers not installed")


def test_normalize_name():
    assert normalize("NAM", "  John   Doe  ") == "John Doe"
    assert normalize("NAM", "Jane\tDoe") == "Jane Doe"

def test_normalize_tin():
    assert normalize("TIN", "123-45-6789") == "123456789"
    assert normalize("TIN", "123 45 6789") == "123456789"


def test_normalize_credit_card():
    """CCN normalization strips spaces and dashes."""
    assert normalize("CCN", "4111 1111 1111 1111") == "4111111111111111"
    assert normalize("CCN", "4111-1111-1111-1111") == "4111111111111111"
    
    with pytest.raises(NormalizationError):
        normalize("CCN", "")


def test_normalize_generic():
    assert normalize("UNK", "  some value  ") == "some value"
    assert normalize("ADR", "  123 Main St.  ") == "123 Main St."

def test_unknown_type():
    # Should fall back to generic normalization
    assert normalize("XYZ", "  test  ") == "test"
