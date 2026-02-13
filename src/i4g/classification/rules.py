import re
from i4g.taxonomy.models import ScoredLabel
from i4g.taxonomy.enums import RequestedAction, DeliveryChannel

from i4g.patterns import (
    BTC_ALL_RE,
    EMAIL_RE,
    ETH_WALLET_RE,
    PHONE_RE,
    URL_RE,
)

# Re-export compiled patterns under the original names for backward compatibility.
BTC_PATTERN = BTC_ALL_RE
ETH_PATTERN = ETH_WALLET_RE
URL_PATTERN = URL_RE
PHONE_PATTERN = PHONE_RE
EMAIL_PATTERN = EMAIL_RE


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
    if BTC_ALL_RE.search(text) or ETH_WALLET_RE.search(text):
        signals["actions"].append(
            ScoredLabel(
                label=RequestedAction.CRYPTO.value,
                confidence=1.0,
                explanation="Detected cryptocurrency wallet address pattern."
            )
        )

    # URL Detection
    if URL_RE.search(text):
        signals["actions"].append(
            ScoredLabel(
                label=RequestedAction.CLICK_LINK.value,
                confidence=1.0,
                explanation="Detected URL/Link pattern."
            )
        )

    # Phone Number Detection
    if PHONE_RE.search(text):
        signals["channel"].append(
            ScoredLabel(
                label=DeliveryChannel.PHONE.value,
                confidence=1.0,
                explanation="Detected phone number pattern."
            )
        )

    # Email Detection
    if EMAIL_RE.search(text):
        signals["channel"].append(
            ScoredLabel(
                label=DeliveryChannel.EMAIL.value,
                confidence=1.0,
                explanation="Detected email address pattern."
            )
        )

    return signals
