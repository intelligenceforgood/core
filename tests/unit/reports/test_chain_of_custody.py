"""Tests for dossier_signatures chain-of-custody extensions.

Covers compute_aggregate_hash() and hash_content() — the two-tier
chain-of-custody functions added for Sprint 3.
"""

from __future__ import annotations

from i4g.reports.dossier_signatures import compute_aggregate_hash, hash_content


def test_compute_aggregate_hash_deterministic() -> None:
    """Aggregate hash is deterministic given the same inputs."""
    hashes = ["abc123", "def456", "ghi789"]
    result1 = compute_aggregate_hash(hashes)
    result2 = compute_aggregate_hash(hashes)
    assert result1 == result2
    assert len(result1) == 64  # SHA-256 hex


def test_compute_aggregate_hash_order_independent() -> None:
    """Aggregate hash sorts inputs so order doesn't matter."""
    h1 = compute_aggregate_hash(["aaa", "bbb", "ccc"])
    h2 = compute_aggregate_hash(["ccc", "aaa", "bbb"])
    assert h1 == h2


def test_compute_aggregate_hash_differs_for_different_inputs() -> None:
    """Different inputs produce different aggregate hashes."""
    h1 = compute_aggregate_hash(["abc"])
    h2 = compute_aggregate_hash(["def"])
    assert h1 != h2


def test_hash_content_string() -> None:
    """hash_content produces a hex digest for string input."""
    result = hash_content("hello world")
    assert isinstance(result, str)
    assert len(result) == 64


def test_hash_content_bytes() -> None:
    """hash_content accepts bytes input."""
    result = hash_content(b"binary data")
    assert isinstance(result, str)
    assert len(result) == 64


def test_hash_content_deterministic() -> None:
    """Same content always produces the same hash."""
    assert hash_content("test") == hash_content("test")


def test_hash_content_different_inputs() -> None:
    """Different content produces different hashes."""
    assert hash_content("a") != hash_content("b")
