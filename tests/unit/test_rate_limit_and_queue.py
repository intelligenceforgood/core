from unittest.mock import patch

import pytest
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from i4g.api.app import REQUEST_LOG, app, rate_limit_middleware

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_request_log(monkeypatch: pytest.MonkeyPatch):
    """A fixture to automatically clear the request log before each test."""

    REQUEST_LOG.clear()
    monkeypatch.setattr("i4g.api.app.MAX_REQUESTS_PER_MINUTE", 10)


async def mock_call_next(request):
    """A dummy function to simulate the 'call_next' in the middleware."""
    return JSONResponse(content={"message": "OK"})


@pytest.mark.anyio
async def test_rate_limiting_direct_call():
    """Unit test the middleware logic directly, bypassing the TestClient."""
    MAX_REQUESTS = 10
    TEST_IP = "127.0.0.1"

    scope = {
        "type": "http",
        "client": ("testclient", 123),
        "headers": [(b"x-forwarded-for", TEST_IP.encode())],
    }
    request = Request(scope)

    with patch("time.time") as mock_time:
        current_time = 1000000.0
        mock_time.return_value = current_time

        # Call middleware 10 times, they should pass
        for _i in range(MAX_REQUESTS):
            await rate_limit_middleware(request, mock_call_next)

        # The 11th call should raise an exception
        with pytest.raises(HTTPException) as excinfo:
            await rate_limit_middleware(request, mock_call_next)

        assert excinfo.value.status_code == 429

        # Move time forward
        mock_time.return_value = current_time + 61

        # The 12th call should now pass
        await rate_limit_middleware(request, mock_call_next)
