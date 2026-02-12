"""Canonical schema definitions for normalized entities.

Defines dataclasses for the normalized representation of extracted entities.
Used by downstream indexing and retrieval systems.
"""

from dataclasses import dataclass


@dataclass
class NormalizedRecord:
    """Unified normalized entity structure.

    Attributes:
        people: List of person names involved in the case.
        organizations: Canonical organization names (e.g., "Binance").
        crypto_assets: Canonical crypto asset symbols or names.
        wallet_addresses: Wallet addresses, lowercased, deduplicated.
        contact_channels: Messaging or communication handles.
        locations: Standardized location names.
        scam_indicators: Terms or patterns associated with fraud activity.
        source_text: Optional original text for reference or debugging.
    """

    people: list[str]
    organizations: list[str]
    crypto_assets: list[str]
    wallet_addresses: list[str]
    contact_channels: list[str]
    locations: list[str]
    scam_indicators: list[str]
    source_text: str | None = None
