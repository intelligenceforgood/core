"""Unit tests for partner indicator feed API (S6-21).

Covers pagination, TLP filtering, rate limiting, API key auth, and audit logging.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


def test_feed_indicator_model() -> None:
    """FeedIndicator model serializes with camelCase aliases."""
    from i4g.api.partner_feed import FeedIndicator

    fi = FeedIndicator(
        indicator_id="test:phone:123",
        category="phone",
        indicator_type="phone_number",
        indicator_value="+1234567890",
        case_count=5,
        loss_sum=10000.0,
        max_risk_score=85.0,
        tlp="TLP:GREEN",
    )
    data = fi.model_dump(by_alias=True)
    assert data["indicatorId"] == "test:phone:123"
    assert data["caseCount"] == 5
    assert data["tlp"] == "TLP:GREEN"


def test_feed_response_model() -> None:
    """FeedResponse model has correct pagination fields."""
    from i4g.api.partner_feed import FeedResponse

    resp = FeedResponse(
        items=[],
        total=0,
        page=1,
        page_size=50,
        has_more=False,
    )
    data = resp.model_dump(by_alias=True)
    assert data["total"] == 0
    assert data["hasMore"] is False


def test_hash_key_deterministic() -> None:
    """ApiKeyStore._hash_key produces consistent SHA-256 digests."""
    from i4g.store.api_key_store import ApiKeyStore

    h1 = ApiKeyStore._hash_key("test-api-key")
    h2 = ApiKeyStore._hash_key("test-api-key")
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex digest


def test_hash_key_different_inputs() -> None:
    """Different inputs produce different hashes."""
    from i4g.store.api_key_store import ApiKeyStore

    h1 = ApiKeyStore._hash_key("key-a")
    h2 = ApiKeyStore._hash_key("key-b")
    assert h1 != h2


def test_rate_limit_allows_within_limit() -> None:
    """Rate limiter allows requests within the configured limit."""
    from i4g.api.partner_feed import _check_rate_limit, _rate_windows

    _rate_windows.clear()
    key_meta = {"key_id": "test-key-rl", "rate_limit_per_minute": 10}
    # Should not raise for first request
    _check_rate_limit(key_meta)


def test_rate_limit_blocks_over_limit() -> None:
    """Rate limiter raises 429 when limit exceeded."""

    from fastapi import HTTPException

    from i4g.api.partner_feed import _check_rate_limit, _rate_windows

    _rate_windows.clear()
    key_meta = {"key_id": "test-key-rl2", "rate_limit_per_minute": 3}

    for _ in range(3):
        _check_rate_limit(key_meta)

    with pytest.raises(HTTPException) as exc_info:
        _check_rate_limit(key_meta)
    assert exc_info.value.status_code == 429


def test_log_feed_access_handles_failure() -> None:
    """_log_feed_access swallows DB errors gracefully."""
    from i4g.api.partner_feed import _log_feed_access

    with patch("i4g.api.partner_feed.build_sql_session_factory", side_effect=Exception("DB down")):
        # Should not raise
        _log_feed_access(
            {"key_id": "k1", "partner_name": "test"},
            endpoint="/feeds/indicators",
            method="GET",
            query_params=None,
            result_count=0,
            response_code=200,
            ip_address="127.0.0.1",
        )
