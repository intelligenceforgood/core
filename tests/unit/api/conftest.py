"""Shared fixtures for core API unit tests."""

from __future__ import annotations

import pytest

from i4g.api.app import REQUEST_LOG


@pytest.fixture(autouse=True)
def _clear_rate_limit_state() -> None:
    """Clear the rate-limit request log before each test.

    The ``REQUEST_LOG`` global in ``i4g.api.app`` accumulates request
    timestamps across test functions.  Without resetting it, earlier
    tests can push the count above ``MAX_REQUESTS_PER_MINUTE`` and
    cause later tests to receive unexpected 429 responses.
    """
    REQUEST_LOG.clear()
