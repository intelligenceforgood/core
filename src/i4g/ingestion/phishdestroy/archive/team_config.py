"""Per-team blob configuration registry for PhishDestroy archive adapters (Sprint 2 Phase D).

Centralises the blob-categorisation defaults that were previously hard-coded as module-private
constants in ``archive/evidence.py``.  Each team entry can override the defaults by supplying
a custom :class:`TeamBlobConfig`; the TWP entry uses the defaults verbatim so Phase C behaviour
is byte-for-byte preserved.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TeamBlobConfig:
    """Per-team file-classification configuration for evidence-blob persistence."""

    photo_suffixes: frozenset[str]
    """Lower-cased suffixes that classify a file as a :attr:`BlobKind.PHOTO` blob."""

    panel_capture_names: tuple[str, ...]
    """Exact file names that classify a file as a :attr:`BlobKind.PANEL_CAPTURE` blob."""

    source_map_suffixes: frozenset[str]
    """Lower-cased suffixes that classify a file as a :attr:`BlobKind.SOURCE_MAP` blob."""


DEFAULT_TEAM_BLOB_CONFIG: TeamBlobConfig = TeamBlobConfig(
    photo_suffixes=frozenset({".png", ".jpg", ".jpeg"}),
    panel_capture_names=("chats.html", "wallets_full.html", "analytics.html", "index.html"),
    source_map_suffixes=frozenset({".map"}),
)
"""Blob-classification defaults matching the Phase C constants in ``evidence.py``."""


@dataclass(frozen=True)
class TeamConfig:
    """Full per-team configuration entry in the generalised team registry."""

    team_name: str
    """Team directory name, e.g. ``"TrustWalletPanel"``."""

    brand: str | None
    """Human-readable brand the team impersonates, or ``None`` if unknown.

    Used for brand-impersonation best-effort writes (Phase D §item 3).
    When ``None``, no brand-impersonation lookup is attempted.
    """

    blob_config: TeamBlobConfig
    """Blob-classification config for evidence-blob persistence."""


TEAM_CONFIG_REGISTRY: dict[str, TeamConfig] = {
    "TrustWalletPanel": TeamConfig(
        team_name="TrustWalletPanel",
        brand="Trust Wallet",
        blob_config=DEFAULT_TEAM_BLOB_CONFIG,
    ),
}
"""Registry mapping team directory names to their :class:`TeamConfig` entries."""


def get_team_config(team_name: str) -> TeamConfig:
    """Return :class:`TeamConfig` for *team_name*, or a synthesized default with ``brand=None``.

    Args:
        team_name: Team directory name, e.g. ``"TrustWalletPanel"``.

    Returns:
        The registered :class:`TeamConfig` when one exists, otherwise a synthesized entry
        using :data:`DEFAULT_TEAM_BLOB_CONFIG` and ``brand=None``.
    """
    return TEAM_CONFIG_REGISTRY.get(team_name) or TeamConfig(
        team_name=team_name,
        brand=None,
        blob_config=DEFAULT_TEAM_BLOB_CONFIG,
    )
