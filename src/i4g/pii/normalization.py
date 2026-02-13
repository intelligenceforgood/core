import logging
import re

LOGGER = logging.getLogger(__name__)


class NormalizationError(ValueError):
    """Raised when a value cannot be normalized for the given type."""


def normalize_email(value: str) -> str:
    """Normalize email address: lowercase, trim, and encode IDN domains via Punycode.

    International domain names (IDN) like ``user@münchen.de`` are converted to
    their ASCII-compatible encoding (ACE) so that downstream HMAC digests are
    deterministic regardless of the Unicode representation the caller supplies.
    """
    if not value:
        raise NormalizationError("Email cannot be empty")

    value = value.strip().lower()
    if "@" not in value:
        raise NormalizationError(f"Invalid email format: {value}")

    local, domain = value.rsplit("@", 1)
    try:
        # Encode each label independently so that mixed ASCII/IDN labels work.
        ace_domain = ".".join(
            label.encode("idna").decode("ascii") if not label.isascii() else label for label in domain.split(".")
        )
    except (UnicodeError, UnicodeDecodeError):
        # If IDNA encoding fails, keep the original domain.
        LOGGER.debug("IDNA encoding failed for domain '%s'; keeping original.", domain)
        ace_domain = domain

    return f"{local}@{ace_domain}"


def normalize_phone(value: str) -> str:
    """Normalize phone number to E.164 format using ``python-phonenumbers``.

    Falls back to basic digit stripping when the library is unavailable or
    parsing fails.
    """
    if not value:
        raise NormalizationError("Phone number cannot be empty")

    try:
        import phonenumbers

        parsed = phonenumbers.parse(value, "US")  # default region for 10-digit numbers
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except ImportError:
        LOGGER.debug("python-phonenumbers not installed; using basic normalization.")
    except Exception:  # noqa: BLE001 — phonenumbers can raise NumberParseException
        pass

    # Fallback: strip non-digit chars (keep leading +)
    cleaned = re.sub(r"[^\d+]", "", value)
    if not cleaned:
        raise NormalizationError(f"Invalid phone format: {value}")
    return cleaned


def normalize_credit_card(value: str) -> str:
    """Normalize credit card number: strip all non-digit characters."""
    if not value:
        raise NormalizationError("Credit card number cannot be empty")
    digits = re.sub(r"[^\d]", "", value)
    if not digits:
        raise NormalizationError(f"Invalid credit card format: {value}")
    return digits

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
    "CCN": normalize_credit_card,
    "UNK": normalize_generic,
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
