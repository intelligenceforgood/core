"""Unit tests for blockchain enrichment service (S6-19)."""

from __future__ import annotations

from unittest.mock import patch


def test_mock_vendor_returns_result() -> None:
    """Mock vendor returns a deterministic result for any wallet address."""
    with patch("i4g.services.enrichment.blockchain._get_config", return_value=("mock", "")):
        from i4g.services.enrichment.blockchain import enrich_wallet

        result = enrich_wallet("0xabcdef1234567890abcdef1234567890abcdef12")
        assert result.address == "0xabcdef1234567890abcdef1234567890abcdef12"
        assert result.vendor == "mock"
        assert result.error is None
        assert len(result.risk_labels) > 0


def test_mock_vendor_cluster() -> None:
    """Mock vendor returns a wallet cluster."""
    with patch("i4g.services.enrichment.blockchain._get_config", return_value=("mock", "")):
        from i4g.services.enrichment.blockchain import get_wallet_cluster

        cluster = get_wallet_cluster("0xaaaa")
        assert cluster is not None
        assert cluster.cluster_id.startswith("mock-cluster-")
        assert "0xaaaa" in cluster.addresses


def test_unconfigured_vendor_falls_back_to_mock() -> None:
    """Unimplemented vendor falls back to mock enrichment."""
    with patch("i4g.services.enrichment.blockchain._get_config", return_value=("trm", "key-123")):
        from i4g.services.enrichment.blockchain import enrich_wallet

        result = enrich_wallet("0x1234")
        # TRM is not yet implemented, so it falls back to mock
        assert result.vendor == "mock"


def test_enrich_wallet_with_no_api_key() -> None:
    """Chainalysis vendor with no API key falls back to mock."""
    with patch("i4g.services.enrichment.blockchain._get_config", return_value=("chainalysis", "")):
        from i4g.services.enrichment.blockchain import enrich_wallet

        result = enrich_wallet("0x1234")
        # No API key → graceful fallback to mock
        assert result.vendor == "mock"


def test_result_dataclass_fields() -> None:
    """BlockchainEnrichmentResult has expected fields."""
    from i4g.services.enrichment.blockchain import BlockchainEnrichmentResult

    result = BlockchainEnrichmentResult(
        address="0xtest",
        network="ethereum",
        vendor="mock",
        risk_labels=[],
        cluster=None,
        exchange_attribution=None,
        error=None,
    )
    assert result.address == "0xtest"
    assert result.network == "ethereum"
    assert result.risk_labels == []
    assert result.cluster is None


def test_wallet_risk_label_dataclass() -> None:
    """WalletRiskLabel dataclass works correctly."""
    from i4g.services.enrichment.blockchain import WalletRiskLabel

    label = WalletRiskLabel(label="sanctions", category="illicit", severity="high", source="chainalysis")
    assert label.label == "sanctions"
    assert label.category == "illicit"
    assert label.severity == "high"
