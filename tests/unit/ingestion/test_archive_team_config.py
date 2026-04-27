"""Unit tests for ``i4g.ingestion.phishdestroy.archive.team_config`` (Sprint 2 Phase D)."""

from __future__ import annotations

from i4g.ingestion.phishdestroy.archive.team_config import (
    DEFAULT_TEAM_BLOB_CONFIG,
    TEAM_CONFIG_REGISTRY,
    TeamBlobConfig,
    TeamConfig,
    get_team_config,
)


class TestDefaultTeamBlobConfig:
    """DEFAULT_TEAM_BLOB_CONFIG values must match the Phase C constants exactly."""

    def test_photo_suffixes_match_phase_c(self) -> None:
        assert DEFAULT_TEAM_BLOB_CONFIG.photo_suffixes == frozenset({".png", ".jpg", ".jpeg"})

    def test_panel_capture_names_match_phase_c(self) -> None:
        assert DEFAULT_TEAM_BLOB_CONFIG.panel_capture_names == (
            "chats.html",
            "wallets_full.html",
            "analytics.html",
            "index.html",
        )

    def test_source_map_suffixes_match_phase_c(self) -> None:
        assert DEFAULT_TEAM_BLOB_CONFIG.source_map_suffixes == frozenset({".map"})

    def test_is_frozen(self) -> None:
        assert isinstance(DEFAULT_TEAM_BLOB_CONFIG, TeamBlobConfig)
        # frozen=True means attempting attribute assignment raises AttributeError.
        import pytest

        with pytest.raises((AttributeError, TypeError)):
            DEFAULT_TEAM_BLOB_CONFIG.photo_suffixes = frozenset()  # type: ignore[misc]


class TestTeamConfigRegistry:
    """TEAM_CONFIG_REGISTRY must contain the TWP entry with the expected values."""

    def test_twp_entry_present(self) -> None:
        assert "TrustWalletPanel" in TEAM_CONFIG_REGISTRY

    def test_twp_brand(self) -> None:
        assert TEAM_CONFIG_REGISTRY["TrustWalletPanel"].brand == "Trust Wallet"

    def test_twp_team_name(self) -> None:
        assert TEAM_CONFIG_REGISTRY["TrustWalletPanel"].team_name == "TrustWalletPanel"

    def test_twp_blob_config_equals_default(self) -> None:
        assert TEAM_CONFIG_REGISTRY["TrustWalletPanel"].blob_config == DEFAULT_TEAM_BLOB_CONFIG


class TestGetTeamConfig:
    """get_team_config registry lookup and miss-with-default behaviour."""

    def test_lookup_hit_returns_registered_entry(self) -> None:
        cfg = get_team_config("TrustWalletPanel")
        assert isinstance(cfg, TeamConfig)
        assert cfg.team_name == "TrustWalletPanel"
        assert cfg.brand == "Trust Wallet"
        assert cfg.blob_config == DEFAULT_TEAM_BLOB_CONFIG

    def test_lookup_miss_returns_default_with_brand_none(self) -> None:
        cfg = get_team_config("UnknownTeam_XYZ")
        assert cfg.team_name == "UnknownTeam_XYZ"
        assert cfg.brand is None
        assert cfg.blob_config == DEFAULT_TEAM_BLOB_CONFIG

    def test_lookup_miss_does_not_pollute_registry(self) -> None:
        get_team_config("SomeNewTeam")
        assert "SomeNewTeam" not in TEAM_CONFIG_REGISTRY
