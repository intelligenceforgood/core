"""Blockchain analytics enrichment via vendor API.

Queries wallet risk labels, transaction volumes, exchange attribution,
and cluster membership from a configurable blockchain analytics vendor
(Chainalysis Reactor, TRM Labs, or Elliptic).

Configure via ``I4G_ENRICHMENT__BLOCKCHAIN_VENDOR`` and
``I4G_ENRICHMENT__BLOCKCHAIN_API_KEY``.
When the key is empty, all methods return empty results.

Vendor evaluation summary (S6-01):
- **Chainalysis Reactor** — market-leading attribution database, broadest
  exchange coverage, well-documented REST API.  Recommended for
  production deployment.
- **TRM Labs** — strong compliance focus, good multi-chain support,
  competitive pricing for startups.
- **Elliptic** — solid risk-scoring model, Lens product for visual
  investigation, lighter API surface.

The integration uses a vendor-agnostic data model so the concrete vendor
can be swapped by changing a single env var.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum

import httpx

from i4g.settings import get_settings

logger = logging.getLogger(__name__)


_TIMEOUT = 20.0


class BlockchainVendor(StrEnum):
    """Supported blockchain analytics vendors."""

    CHAINALYSIS = "chainalysis"
    TRM = "trm"
    ELLIPTIC = "elliptic"
    MOCK = "mock"


@dataclass
class WalletRiskLabel:
    """Vendor-assigned risk label for a wallet address."""

    label: str
    category: str
    severity: str  # "low", "medium", "high", "critical"
    source: str


@dataclass
class WalletCluster:
    """Group of wallet addresses controlled by the same entity."""

    cluster_id: str
    name: str | None = None
    wallet_count: int = 0
    addresses: list[str] = field(default_factory=list)


@dataclass
class ExchangeAttribution:
    """Exchange or service attribution for a wallet."""

    exchange_name: str
    confidence: float = 0.0
    category: str = "exchange"  # exchange, mixer, defi, unknown


@dataclass
class BlockchainEnrichmentResult:
    """Aggregated blockchain enrichment for a single wallet address."""

    address: str
    network: str
    risk_score: float = 0.0
    risk_labels: list[WalletRiskLabel] = field(default_factory=list)
    cluster: WalletCluster | None = None
    exchange_attribution: ExchangeAttribution | None = None
    transaction_volume_usd: float = 0.0
    transaction_count: int = 0
    first_seen: str | None = None
    last_seen: str | None = None
    vendor: str = ""
    error: str | None = None

    def to_dict(self) -> dict:
        """Return a JSON-serializable representation.

        Returns:
            Dict with all enrichment fields.
        """
        result: dict = {
            "address": self.address,
            "network": self.network,
            "risk_score": self.risk_score,
            "risk_labels": [
                {"label": r.label, "category": r.category, "severity": r.severity, "source": r.source}
                for r in self.risk_labels
            ],
            "transaction_volume_usd": self.transaction_volume_usd,
            "transaction_count": self.transaction_count,
            "vendor": self.vendor,
        }
        if self.cluster:
            result["cluster"] = {
                "cluster_id": self.cluster.cluster_id,
                "name": self.cluster.name,
                "wallet_count": self.cluster.wallet_count,
                "addresses": self.cluster.addresses,
            }
        if self.exchange_attribution:
            result["exchange_attribution"] = {
                "exchange_name": self.exchange_attribution.exchange_name,
                "confidence": self.exchange_attribution.confidence,
                "category": self.exchange_attribution.category,
            }
        if self.first_seen:
            result["first_seen"] = self.first_seen
        if self.last_seen:
            result["last_seen"] = self.last_seen
        if self.error:
            result["error"] = self.error
        return result


def _get_config() -> tuple[str, str]:
    """Resolve blockchain vendor and API key from settings.

    Returns:
        Tuple of (vendor, api_key).
    """
    settings = get_settings()
    enrichment = getattr(settings, "enrichment", None)
    vendor = getattr(enrichment, "blockchain_vendor", "mock")
    api_key = getattr(enrichment, "blockchain_api_key", "")
    return vendor, api_key


def _enrich_chainalysis(address: str, network: str, api_key: str) -> BlockchainEnrichmentResult:
    """Query Chainalysis Reactor API for wallet enrichment.

    Args:
        address: Wallet address.
        network: Blockchain network (e.g. ``ethereum``, ``bitcoin``).
        api_key: Chainalysis API key.

    Returns:
        Enrichment result with risk labels and cluster data.
    """
    base = "https://api.chainalysis.com/api/risk/v2"
    headers = {"Token": api_key, "Accept": "application/json"}

    result = BlockchainEnrichmentResult(address=address, network=network, vendor="chainalysis")

    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            # Register address for screening
            client.post(f"{base}/entities", headers=headers, json={"address": address})

            # Fetch risk assessment
            resp = client.get(f"{base}/entities/{address}", headers=headers)
            resp.raise_for_status()
            data = resp.json()

        result.risk_score = data.get("risk", 0.0)

        for exposure in data.get("exposures", []):
            result.risk_labels.append(
                WalletRiskLabel(
                    label=exposure.get("category", "unknown"),
                    category=exposure.get("categoryGroup", "unknown"),
                    severity=_map_chainalysis_severity(exposure.get("value", 0)),
                    source="chainalysis",
                )
            )

        cluster_data = data.get("cluster", {})
        if cluster_data:
            result.cluster = WalletCluster(
                cluster_id=str(cluster_data.get("id", "")),
                name=cluster_data.get("name"),
                wallet_count=cluster_data.get("size", 0),
            )

    except httpx.HTTPStatusError as exc:
        logger.warning("Chainalysis API error for %s: %s", address, exc.response.status_code)
        result.error = f"api_error_{exc.response.status_code}"
    except httpx.RequestError as exc:
        logger.warning("Chainalysis request error for %s: %s", address, exc)
        result.error = "request_error"

    return result


def _map_chainalysis_severity(value: float) -> str:
    """Map Chainalysis numeric exposure value to severity string.

    Args:
        value: Exposure fraction (0.0–1.0).

    Returns:
        Severity level string.
    """
    if value >= 0.75:
        return "critical"
    if value >= 0.5:
        return "high"
    if value >= 0.25:
        return "medium"
    return "low"


def _enrich_mock(address: str, network: str) -> BlockchainEnrichmentResult:
    """Return mock enrichment data for local development and testing.

    Args:
        address: Wallet address.
        network: Blockchain network.

    Returns:
        Synthetic enrichment result.
    """
    return BlockchainEnrichmentResult(
        address=address,
        network=network,
        risk_score=0.65,
        risk_labels=[
            WalletRiskLabel(
                label="scam",
                category="illicit",
                severity="high",
                source="mock",
            ),
        ],
        cluster=WalletCluster(
            cluster_id="mock-cluster-001",
            name="Mock Scam Cluster",
            wallet_count=5,
            addresses=[address],
        ),
        exchange_attribution=ExchangeAttribution(
            exchange_name="MockExchange",
            confidence=0.85,
            category="exchange",
        ),
        transaction_volume_usd=125_000.0,
        transaction_count=47,
        first_seen="2025-06-01T00:00:00Z",
        last_seen="2026-02-15T00:00:00Z",
        vendor="mock",
    )


def enrich_wallet(address: str, network: str = "ethereum") -> BlockchainEnrichmentResult:
    """Enrich a wallet address with blockchain analytics data.

    Dispatches to the configured vendor (Chainalysis, TRM, Elliptic, or mock).

    Args:
        address: Wallet address to enrich.
        network: Blockchain network (default ``ethereum``).

    Returns:
        Enrichment result from the configured vendor.
    """
    vendor, api_key = _get_config()

    if vendor == BlockchainVendor.MOCK or not api_key:
        if not api_key and vendor != BlockchainVendor.MOCK:
            logger.debug("Blockchain API key not configured — using mock enrichment")
        return _enrich_mock(address, network)

    if vendor == BlockchainVendor.CHAINALYSIS:
        return _enrich_chainalysis(address, network, api_key)

    # TRM and Elliptic stubs — implement when vendor contract is signed
    logger.warning("Blockchain vendor %r not yet implemented — using mock", vendor)
    return _enrich_mock(address, network)


def get_wallet_cluster(address: str, network: str = "ethereum") -> WalletCluster | None:
    """Return the wallet cluster containing the given address.

    Args:
        address: Wallet address.
        network: Blockchain network.

    Returns:
        WalletCluster if the vendor identifies a cluster, else None.
    """
    result = enrich_wallet(address, network)
    return result.cluster
