"""Blocklist-based post-extraction filter module.

Filters out known false positives *after* extraction.  The blocklist is
loaded from a TOML config file so non-engineers can update it without
code changes.

Unlike other modules, the blocklist doesn't *produce* entities — it marks
existing entities for removal.  It implements ``ModuleProtocol`` for registry
consistency, but its ``extract()`` is a no-op.  The orchestrator calls
``is_blocklisted()`` during the merge phase.
"""

from __future__ import annotations

import logging
from pathlib import Path

from i4g.extraction.types import ScoredEntity

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Built-in blocklist — covers the known false-positive patterns from
# ner_rules._NON_PERSON_BLOCKLIST plus additional type-specific entries.
# This is the fallback when no TOML config file is available.
# ---------------------------------------------------------------------------

_DEFAULT_BLOCKLIST: dict[str, frozenset[str]] = {
    "person": frozenset(
        s.lower()
        for s in [
            # Banking / financial field labels
            "Account Name",
            "Account Number",
            "Account Type",
            "Bank Account",
            "Bank Address",
            "Bank Branch",
            "Bank Code",
            "Bank Details",
            "Bank Name",
            "Branch Code",
            "Branch Name",
            "Card Number",
            "Credit Card",
            "Debit Card",
            "Iban Number",
            "Loan Number",
            "Payment Method",
            "Payment Reference",
            "Pin Number",
            "Reference Number",
            "Routing Number",
            "Sort Code",
            "Swift Code",
            "Transaction Id",
            "Transfer Details",
            "Wire Transfer",
            # Scam / fraud terminology
            "Advance Fee",
            "Money Mule",
            "Money Order",
            "Money Transfer",
            "Gift Card",
            "Gift Cards",
            "Identity Theft",
            "Investment Scam",
            "Lottery Scam",
            "Phone Scam",
            "Prize Scam",
            "Romance Scam",
            "Tech Support",
            # Generic report / form labels
            "Case Number",
            "Case Status",
            "Contact Details",
            "Contact Information",
            "Email Address",
            "First Name",
            "Full Name",
            "Last Name",
            "Phone Number",
            "Postal Code",
            "Social Security",
            "Zip Code",
            # Common false positives from LLM extraction
            "Wells Fargo",
            "Chase Bank",
            "On Behalf",
            "Contact Needed",
            "Henderson Internal",
            "Revenue Service",
            "United States",
            "New York",
            "On Mon",
            "On Wed",
            "On Tue",
            "On Thu",
            "On Fri",
            "On Sat",
            "On Sun",
            "Original Message",
            "Online Fraud",
            "Customer Service",
        ]
    ),
}


def _load_blocklist_from_toml(path: Path) -> dict[str, frozenset[str]] | None:
    """Load a blocklist from a TOML file.

    Expected format::

        [person]
        values = ["Wells Fargo", "Chase Bank", ...]

        [organization]
        values = ["Some Org", ...]

    Args:
        path: Path to the TOML file.

    Returns:
        Dict mapping entity type to frozenset of lowercased blocked values,
        or ``None`` if the file doesn't exist or can't be parsed.
    """
    if not path.is_file():
        return None

    try:
        import tomllib
    except ModuleNotFoundError:  # Python < 3.11
        import tomli as tomllib  # type: ignore[no-redef]

    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except Exception:
        logger.warning("Failed to load blocklist from %s", path, exc_info=True)
        return None

    result: dict[str, frozenset[str]] = {}
    for entity_type, section in data.items():
        if isinstance(section, dict) and "values" in section:
            result[entity_type] = frozenset(v.lower() for v in section["values"] if isinstance(v, str))
    return result


class BlocklistModule:
    """Post-extraction filter that removes known false positives.

    Args:
        config_path: Optional path to a TOML blocklist config file.
            If not provided or the file doesn't exist, the built-in
            default blocklist is used.
    """

    def __init__(self, config_path: Path | None = None) -> None:
        self._blocklist = _DEFAULT_BLOCKLIST.copy()
        if config_path is not None:
            custom = _load_blocklist_from_toml(config_path)
            if custom:
                # Merge: custom entries replace defaults per type
                for etype, values in custom.items():
                    existing = self._blocklist.get(etype, frozenset())
                    self._blocklist[etype] = existing | values

    @property
    def name(self) -> str:
        return "blocklist"

    @property
    def authority(self) -> dict[str, float]:
        return {}  # Blocklist doesn't produce entities.

    def extract(self, text: str) -> list[ScoredEntity]:
        """No-op — the blocklist is a filter, not a producer."""
        return []

    def is_blocklisted(self, entity_type: str, canonical_value: str) -> bool:
        """Check whether a value is on the blocklist for its type.

        Args:
            entity_type: Canonical entity type.
            canonical_value: Normalized entity value.

        Returns:
            True if the value should be filtered out.
        """
        blocked = self._blocklist.get(entity_type, frozenset())
        return canonical_value.lower() in blocked
