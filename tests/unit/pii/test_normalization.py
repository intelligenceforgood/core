import pytest
from i4g.pii.normalization import normalize, NormalizationError

def test_normalize_email():
    assert normalize("EID", "Test@Example.COM") == "test@example.com"
    assert normalize("EID", "  user@domain.org  ") == "user@domain.org"
    
    with pytest.raises(NormalizationError):
        normalize("EID", "invalid-email")
        
    with pytest.raises(NormalizationError):
        normalize("EID", "")

def test_normalize_phone():
    assert normalize("PHN", "+1-555-0100") == "+15550100"
    assert normalize("PHN", "(555) 010-0100") == "5550100100"
    
    with pytest.raises(NormalizationError):
        normalize("PHN", "")

def test_normalize_name():
    assert normalize("NAM", "  John   Doe  ") == "John Doe"
    assert normalize("NAM", "Jane\tDoe") == "Jane Doe"

def test_normalize_tin():
    assert normalize("TIN", "123-45-6789") == "123456789"
    assert normalize("TIN", "123 45 6789") == "123456789"

def test_normalize_generic():
    assert normalize("UNK", "  some value  ") == "some value"
    assert normalize("ADR", "  123 Main St.  ") == "123 Main St."

def test_unknown_type():
    # Should fall back to generic normalization
    assert normalize("XYZ", "  test  ") == "test"
