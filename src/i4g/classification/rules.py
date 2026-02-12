import re
from i4g.taxonomy.models import ScoredLabel
from i4g.taxonomy.enums import RequestedAction, DeliveryChannel

# Regex Patterns
# Note: These are simplified patterns for demonstration. 
# Production systems would use more robust libraries or patterns.

# Bitcoin (Legacy, Segwit, Bech32)
BTC_PATTERN = r"\b(bc1|[13])[a-zA-HJ-NP-Z0-9]{25,39}\b"
# Ethereum (0x + 40 hex chars)
ETH_PATTERN = r"\b0x[a-fA-F0-9]{40}\b"

# URLs (http/https)
URL_PATTERN = r"https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+"

# Phone Numbers (US-centric but flexible)
# Matches: 123-456-7890, (123) 456-7890, 123.456.7890, +1 123 456 7890
PHONE_PATTERN = r"(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"

# Email Addresses
EMAIL_PATTERN = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"


def detect_signals(text: str) -> dict[str, list[ScoredLabel]]:
    """
    Detect deterministic signals in the text using regex patterns.
    
    Returns a dictionary mapping taxonomy categories (actions, channel) 
    to lists of ScoredLabel objects.
    """
    signals: dict[str, list[ScoredLabel]] = {
        "actions": [],
        "channel": []
    }
    
    # Crypto Detection
    if re.search(BTC_PATTERN, text) or re.search(ETH_PATTERN, text):
        signals["actions"].append(
            ScoredLabel(
                label=RequestedAction.CRYPTO.value,
                confidence=1.0,
                explanation="Detected cryptocurrency wallet address pattern."
            )
        )

    # URL Detection
    if re.search(URL_PATTERN, text):
        signals["actions"].append(
            ScoredLabel(
                label=RequestedAction.CLICK_LINK.value,
                confidence=1.0,
                explanation="Detected URL/Link pattern."
            )
        )

    # Phone Number Detection
    if re.search(PHONE_PATTERN, text):
        signals["channel"].append(
            ScoredLabel(
                label=DeliveryChannel.PHONE.value,
                confidence=1.0,
                explanation="Detected phone number pattern."
            )
        )

    # Email Detection
    if re.search(EMAIL_PATTERN, text):
        signals["channel"].append(
            ScoredLabel(
                label=DeliveryChannel.EMAIL.value,
                confidence=1.0,
                explanation="Detected email address pattern."
            )
        )

    return signals
