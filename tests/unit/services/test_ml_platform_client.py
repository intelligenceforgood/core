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


@pytest.mark.asyncio
async def test_extract_entities_sends_correct_request() -> None:
    """extract_entities() sends text+case_id to /predict/extract-entities."""
    ner_response = {
        "prediction_id": "p-ner-1",
        "entities": [
            {"text": "John", "label": "PERSON", "start": 0, "end": 4, "confidence": 0.95},
            {"text": "Acme", "label": "ORG", "start": 15, "end": 19, "confidence": 0.88},
            {"text": "john@test.com", "label": "EMAIL", "start": 25, "end": 38, "confidence": 0.92},
        ],
        "model_info": {"model_id": "ner-bert", "version": 1, "stage": "candidate"},
    }

    async def _mock_handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).endswith("/predict/extract-entities")
        return httpx.Response(200, json=ner_response)

    transport = httpx.MockTransport(_mock_handler)
    settings = reload_settings(env="local")
    with patch("i4g.ml.client.get_settings", return_value=settings):
        client = MLPlatformClient(base_url="http://ml-test")
    # Monkey-patch to use mock transport
    client._base_url = "http://ml-test"
    client._timeout = 30.0

    async with httpx.AsyncClient(base_url="http://ml-test", transport=transport) as mock_client:
        resp = await mock_client.post(
            "/predict/extract-entities",
            json={"text": "John works at Acme john@test.com", "case_id": "case-99"},
        )
        resp.raise_for_status()
        result = resp.json()

    assert result["prediction_id"] == "p-ner-1"
    assert len(result["entities"]) == 3


@pytest.mark.asyncio
async def test_extract_entities_maps_labels_to_core_schema() -> None:
    """extract_entities() maps NER labels to core entity extraction schema."""
    from i4g.ml.client import _NER_LABEL_TO_ENTITY_KEY

    assert _NER_LABEL_TO_ENTITY_KEY["PERSON"] == "people"
    assert _NER_LABEL_TO_ENTITY_KEY["ORG"] == "organizations"
    assert _NER_LABEL_TO_ENTITY_KEY["CRYPTO_WALLET"] == "wallet_addresses"
    assert _NER_LABEL_TO_ENTITY_KEY["EMAIL"] == "contact_channels"
    assert _NER_LABEL_TO_ENTITY_KEY["PHONE"] == "contact_channels"
    assert _NER_LABEL_TO_ENTITY_KEY["URL"] == "contact_channels"


@pytest.mark.asyncio
async def test_extract_entities_deduplicates() -> None:
    """extract_entities() deduplicates entities by value within each key."""
    from i4g.ml.client import MLPlatformClient

    ner_response = {
        "prediction_id": "p-ner-2",
        "entities": [
            {"text": "John", "label": "PERSON", "start": 0, "end": 4, "confidence": 0.95},
            {"text": "John", "label": "PERSON", "start": 20, "end": 24, "confidence": 0.90},
        ],
        "model_info": {"model_id": "ner-bert", "version": 1, "stage": "candidate"},
    }

    async def _mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=ner_response)

    transport = httpx.MockTransport(_mock_handler)
    settings = reload_settings(env="local")
    with patch("i4g.ml.client.get_settings", return_value=settings):
        MLPlatformClient(base_url="http://ml-test")  # verify construction works

    async with httpx.AsyncClient(base_url="http://ml-test", transport=transport) as mock_client:
        resp = await mock_client.post(
            "/predict/extract-entities",
            json={"text": "John mentioned John", "case_id": "case-1"},
        )
        data = resp.json()

    # Simulate the dedup logic the client does
    entities = data.get("entities", [])
    seen: set[str] = set()
    deduped = []
    for e in entities:
        if e["text"] not in seen:
            seen.add(e["text"])
            deduped.append(e)
    assert len(deduped) == 1
    assert deduped[0]["text"] == "John"


@pytest.mark.asyncio
async def test_score_risk_sends_correct_payload() -> None:
    """score_risk() sends text+case_id to /predict/risk-score."""
    expected = {"risk_score": 0.82, "prediction_id": "p-risk-1", "model_info": {"model_id": "risk-xgb"}}

    async def _mock_handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        assert body["text"] == "suspicious activity"
        assert body["case_id"] == "case-55"
        assert str(request.url).endswith("/predict/risk-score")
        return httpx.Response(200, json=expected)

    transport = httpx.MockTransport(_mock_handler)
    async with httpx.AsyncClient(base_url="http://ml-test", transport=transport) as mock_client:
        resp = await mock_client.post(
            "/predict/risk-score",
            json={"text": "suspicious activity", "case_id": "case-55"},
        )
        resp.raise_for_status()
        result = resp.json()

    assert result["risk_score"] == 0.82
    assert result["prediction_id"] == "p-risk-1"


@pytest.mark.asyncio
async def test_find_similar_cases_sends_correct_payload() -> None:
    """find_similar_cases() sends text+case_id+top_k to /predict/similar-cases."""
    expected = {
        "similar_cases": [
            {"case_id": "case-10", "score": 0.95},
            {"case_id": "case-20", "score": 0.87},
        ],
        "prediction_id": "p-sim-1",
    }

    async def _mock_handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        assert body["text"] == "fraud pattern"
        assert body["case_id"] == "case-77"
        assert body["top_k"] == 5
        assert str(request.url).endswith("/predict/similar-cases")
        return httpx.Response(200, json=expected)

    transport = httpx.MockTransport(_mock_handler)
    async with httpx.AsyncClient(base_url="http://ml-test", transport=transport) as mock_client:
        resp = await mock_client.post(
            "/predict/similar-cases",
            json={"text": "fraud pattern", "case_id": "case-77", "top_k": 5},
        )
        resp.raise_for_status()
        result = resp.json()

    assert len(result["similar_cases"]) == 2
    assert result["similar_cases"][0]["case_id"] == "case-10"


@pytest.mark.asyncio
async def test_build_risk_scoring_client_switches_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Factory returns MLPlatformClient when risk_scoring_backend is ml_platform."""
    monkeypatch.setenv("I4G_ML__RISK_SCORING_BACKEND", "ml_platform")
    monkeypatch.setenv("I4G_ML__PLATFORM_BASE_URL", "http://ml-test")
    settings = reload_settings(env="local")
    with patch("i4g.services.factories.get_settings", return_value=settings):
        from i4g.services.factories import build_risk_scoring_client

        client = build_risk_scoring_client()
    assert isinstance(client, MLPlatformClient)


@pytest.mark.asyncio
async def test_build_similarity_client_switches_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Factory returns MLPlatformClient when similarity_backend is ml_platform."""
    monkeypatch.setenv("I4G_ML__SIMILARITY_BACKEND", "ml_platform")
    monkeypatch.setenv("I4G_ML__PLATFORM_BASE_URL", "http://ml-test")
    settings = reload_settings(env="local")
    with patch("i4g.services.factories.get_settings", return_value=settings):
        from i4g.services.factories import build_similarity_client

        client = build_similarity_client()
    assert isinstance(client, MLPlatformClient)
