"""PhishDestroy ingestion package for the i4g core service."""

from __future__ import annotations

# Controlled vocabulary for PhishDestroy source identifiers.
# Must match provenance §3 verbatim — do not edit without updating the contract file.
ALLOWED_PHISHDESTROY_SOURCES: frozenset[str] = frozenset(
    [
        "phishdestroy.destroylist",
        "phishdestroy.archive.iocs",
        "phishdestroy.archive.chat",
        "phishdestroy.archive.damage",
        "phishdestroy.archive.infrastructure",
        "phishdestroy.archive.brands",
        "phishdestroy.actors",
        "phishdestroy.registrants",
        "blocklist.metamask",
        "blocklist.scamsniffer",
        "blocklist.openphish",
        "blocklist.seal",
        "blocklist.enkrypt",
        "blocklist.phishdestroy",
    ]
)

__all__ = ["ALLOWED_PHISHDESTROY_SOURCES"]
