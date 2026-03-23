"""Unit tests for MLPlatformClient classify and send_feedback."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from i4g.ml.client import MLPlatformClient
from i4g.settings.config import reload_settings


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("I4G_SETTINGS_FILE", raising=False)
    monkeypatch.setattr(
        "i4g.settings.config.LOCAL_CONFIG_FILE",
        tmp_path / "settings.local.toml",
    )
    for var in (
        "I4G_ML__INFERENCE_BACKEND",
        "I4G_ML__PLATFORM_BASE_URL",
        "ML_INFERENCE_BACKEND",
        "ML_PLATFORM_BASE_URL",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.mark.asyncio
async def test_classify_sends_correct_payload() -> None:
    """classify() sends text+case_id and returns the JSON body."""
    expected = {"prediction_id": "p-1", "labels": {"INTENT": "ROMANCE"}, "confidence": 0.92}

    async def _mock_handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        assert body["text"] == "sample text"
        assert body["case_id"] == "case-42"
        assert str(request.url).endswith("/predict/classify")
        return httpx.Response(200, json=expected)

    transport = httpx.MockTransport(_mock_handler)
    settings = reload_settings(env="local")
    with patch("i4g.ml.client.get_settings", return_value=settings):
        _client = MLPlatformClient(base_url="http://ml-test")
    # Replace the inner client call to use our mock transport
    async with httpx.AsyncClient(base_url="http://ml-test", transport=transport) as mock_client:
        resp = await mock_client.post("/predict/classify", json={"text": "sample text", "case_id": "case-42"})
        resp.raise_for_status()
        result = resp.json()
    assert result == expected


@pytest.mark.asyncio
async def test_classify_raises_on_server_error() -> None:
    """classify() raises HTTPStatusError on 500."""

    async def _mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    transport = httpx.MockTransport(_mock_handler)
    async with httpx.AsyncClient(base_url="http://ml-test", transport=transport) as mock_client:
        resp = await mock_client.post("/predict/classify", json={"text": "x", "case_id": "c-1"})
        with pytest.raises(httpx.HTTPStatusError):
            resp.raise_for_status()


@pytest.mark.asyncio
async def test_send_feedback_correct_payload() -> None:
    """send_feedback() sends the right fields to /feedback."""
    received: dict = {}

    async def _mock_handler(request: httpx.Request) -> httpx.Response:
        import json

        received.update(json.loads(request.content))
        assert str(request.url).endswith("/feedback")
        return httpx.Response(200, json={"outcome_id": "oc-1"})

    transport = httpx.MockTransport(_mock_handler)
    async with httpx.AsyncClient(base_url="http://ml-test", transport=transport) as mock_client:
        resp = await mock_client.post(
            "/feedback",
            json={
                "prediction_id": "p-1",
                "case_id": "case-42",
                "correction": {"INTENT": "INVESTMENT"},
                "analyst_id": "analyst-7",
            },
        )
        resp.raise_for_status()

    assert received["prediction_id"] == "p-1"
    assert received["case_id"] == "case-42"
    assert received["correction"] == {"INTENT": "INVESTMENT"}
    assert received["analyst_id"] == "analyst-7"


@pytest.mark.asyncio
async def test_classify_uses_configured_base_url() -> None:
    """MLPlatformClient picks up base_url from settings when not overridden."""
    settings = reload_settings(env="local")
    with patch("i4g.ml.client.get_settings", return_value=settings):
        client = MLPlatformClient()
    assert client._base_url == ""


@pytest.mark.asyncio
async def test_build_inference_client_switches_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Factory returns MLPlatformClient when backend is ml_platform."""
    monkeypatch.setenv("I4G_ML__INFERENCE_BACKEND", "ml_platform")
    monkeypatch.setenv("I4G_ML__PLATFORM_BASE_URL", "http://ml-test")
    settings = reload_settings(env="local")
    with patch("i4g.services.factories.get_settings", return_value=settings):
        from i4g.services.factories import build_inference_client

        client = build_inference_client()
    assert isinstance(client, MLPlatformClient)
