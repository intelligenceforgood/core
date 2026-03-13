"""Tests for the LEA referral engine.

Covers LeaReferralEngine.get_suggestions() with entity and campaign evaluation.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from i4g.services.lea_referral import LeaReferralEngine

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_analytics_store() -> MagicMock:
    """Create a mock AnalyticsStore."""
    store = MagicMock()
    store.list_entity_stats.return_value = [
        {
            "entity_type": "crypto_wallet",
            "canonical_value": "0xHIGHRISK",
            "case_count": 10,
            "loss_sum": 100000.0,
            "risk_score": 0.9,
            "ecx_hit": True,
        },
        {
            "entity_type": "bank_account",
            "canonical_value": "1234567890",
            "case_count": 2,
            "loss_sum": 5000.0,
            "risk_score": 0.3,
            "ecx_hit": False,
        },
    ]
    return store


@pytest.fixture()
def mock_campaign_store() -> MagicMock:
    """Create a mock ThreatCampaignStore."""
    store = MagicMock()
    store.list_campaigns.return_value = [
        {
            "id": "camp-1",
            "name": "Major Ring",
            "status": "active",
        },
    ]
    store.get_campaign_cases.return_value = [{"case_id": f"c{i}"} for i in range(10)]
    return store


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_engine_returns_suggestions(mock_analytics_store, mock_campaign_store) -> None:
    """Engine produces suggestions for entities meeting thresholds."""
    engine = LeaReferralEngine(
        analytics_store=mock_analytics_store,
        campaign_store=mock_campaign_store,
    )
    suggestions = engine.get_suggestions(limit=10)
    assert len(suggestions) >= 1
    # The high-risk wallet should qualify
    wallet_suggestions = [s for s in suggestions if "0xHIGHRISK" in s.target_id]
    assert len(wallet_suggestions) == 1
    assert wallet_suggestions[0].loss_sum > 0


def test_engine_respects_limit(mock_analytics_store, mock_campaign_store) -> None:
    """Engine caps results at the given limit."""
    engine = LeaReferralEngine(
        analytics_store=mock_analytics_store,
        campaign_store=mock_campaign_store,
    )
    suggestions = engine.get_suggestions(limit=1)
    assert len(suggestions) <= 1


def test_engine_excludes_low_risk_entities(mock_analytics_store, mock_campaign_store) -> None:
    """Low-risk entities should not appear as suggestions."""
    engine = LeaReferralEngine(
        analytics_store=mock_analytics_store,
        campaign_store=mock_campaign_store,
    )
    suggestions = engine.get_suggestions(limit=50)
    low_risk = [s for s in suggestions if "1234567890" in s.target_id]
    assert len(low_risk) == 0
