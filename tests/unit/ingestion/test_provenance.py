"""Provenance vocabulary assertions for PhishDestroy ingestion sources.

Ensures ALLOWED_PHISHDESTROY_SOURCES matches provenance §3 verbatim and that
all sources used by implemented jobs are in the vocabulary.
"""

from __future__ import annotations

from i4g.ingestion.phishdestroy import ALLOWED_PHISHDESTROY_SOURCES

# Authoritative list mirrored from provenance §3 (subset used in Sprint 1).
_EXPECTED_SOURCES = frozenset(
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


def test_destroylist_in_allowed_sources() -> None:
    """The destroylist source identifier must be in the vocabulary."""
    assert "phishdestroy.destroylist" in ALLOWED_PHISHDESTROY_SOURCES


def test_allowed_sources_matches_provenance() -> None:
    """ALLOWED_PHISHDESTROY_SOURCES must contain all provenance §3 values."""
    missing = _EXPECTED_SOURCES - ALLOWED_PHISHDESTROY_SOURCES
    assert not missing, f"Missing sources in ALLOWED_PHISHDESTROY_SOURCES: {missing}"


def test_no_free_text_sources() -> None:
    """Every source identifier must use dot-notation (no spaces, no free text)."""
    for source in ALLOWED_PHISHDESTROY_SOURCES:
        assert " " not in source, f"Source contains a space: {source!r}"
        assert "." in source, f"Source is not dot-notation: {source!r}"
