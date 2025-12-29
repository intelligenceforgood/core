import re
from typing import Optional

class NormalizationError(ValueError):
    """Raised when a value cannot be normalized for the given type."""
    pass

def normalize_email(value: str) -> str:
    """
    Normalize email address: lowercase, trim whitespace.
    TODO: Punycode handling.
    """
    if not value:
        raise NormalizationError("Email cannot be empty")
    
    value = value.strip().lower()
    if "@" not in value:
        raise NormalizationError(f"Invalid email format: {value}")
    
    return value

def normalize_phone(value: str) -> str:
    """
    Normalize phone number to E.164 format (basic implementation).
    Strips non-digit characters (except leading +).
    """
    if not value:
        raise NormalizationError("Phone number cannot be empty")
    
    # Remove all whitespace, parens, dashes
    cleaned = re.sub(r'[^\d+]', '', value)
    
    if not cleaned:
        raise NormalizationError(f"Invalid phone format: {value}")
        
    # Basic E.164 check (must start with + or be convertible)
    # For now, we just return the cleaned version.
    # TODO: Use python-phonenumbers for robust E.164 formatting
    
    return cleaned

def normalize_name(value: str) -> str:
    """
    Normalize person name: collapse whitespace, strip.
    """
    if not value:
        raise NormalizationError("Name cannot be empty")
    
    # Collapse multiple spaces to single space
    return re.sub(r'\s+', ' ', value.strip())

def normalize_tin(value: str) -> str:
    """
    Normalize TIN/SSN: remove separators.
    """
    if not value:
        raise NormalizationError("TIN cannot be empty")
    
    # Remove dashes and spaces
    return re.sub(r'[\s-]', '', value)

def normalize_generic(value: str) -> str:
    """
    Generic normalization: strip whitespace.
    """
    if not value:
        raise NormalizationError("Value cannot be empty")
    return value.strip()

NORMALIZERS = {
    "EID": normalize_email,
    "PHN": normalize_phone,
    "NAM": normalize_name,
    "TIN": normalize_tin,
    "UNK": normalize_generic,
    # Add other types mapping to generic or specific normalizers
    "ADR": normalize_generic,
    "DOB": normalize_generic,
    "PID": normalize_generic,
    "SID": normalize_generic,
    "EMP": normalize_generic,
    "ETX": normalize_generic,
    "STX": normalize_generic,
    "GOV": normalize_generic,
    "CCN": normalize_generic, # Should probably strip spaces/dashes
    "BAN": normalize_generic,
    "IBN": normalize_generic,
    "RTN": normalize_generic,
    "SWF": normalize_generic,
    "ACH": normalize_generic,
    "BTC": normalize_generic,
    "ETH": normalize_generic,
    "WLT": normalize_generic,
    "IPA": normalize_generic,
    "ASN": normalize_generic,
    "MAC": normalize_generic,
    "DID": normalize_generic,
    "BFP": normalize_generic,
    "CID": normalize_generic,
    "HID": normalize_generic,
    "MRN": normalize_generic,
    "NHI": normalize_generic,
    "BIO": normalize_generic,
    "VIN": normalize_generic,
    "LPL": normalize_generic,
    "DOC": normalize_generic,
    "LOC": normalize_generic,
    "PLC": normalize_generic,
}

def normalize(pii_type: str, value: str) -> str:
    """
    Normalize a PII value based on its type.
    
    Args:
        pii_type: The 3-char PII type prefix (e.g., 'EID', 'PHN').
        value: The raw value to normalize.
        
    Returns:
        The normalized string.
        
    Raises:
        NormalizationError: If the value is invalid for the type.
    """
    if pii_type not in NORMALIZERS:
        # Fallback to generic normalization if type is unknown but valid 3-char
        # Or should we raise? Design says "reject-on-invalid per prefix".
        # For now, let's allow unknown types but warn/log? 
        # Or strictly follow the catalog.
        # Let's default to generic for now to be safe, or raise if strict.
        # Given "reject-on-invalid per prefix", maybe we should be strict about KNOWN types.
        # But for "UNK" type it uses generic.
        return normalize_generic(value)
        
    return NORMALIZERS[pii_type](value)
