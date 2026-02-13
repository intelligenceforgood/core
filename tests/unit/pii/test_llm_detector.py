"""Tests for LLM-assisted PII detection (F3)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from i4g.pii.detectors import PiiMatch
from i4g.pii.llm_detector import LlmPiiDetector, reset_circuit_breaker


@pytest.fixture(autouse=True)
def _reset_breaker():
    """Ensure the circuit breaker is reset before/after every test."""
    reset_circuit_breaker()
    yield
    reset_circuit_breaker()


@pytest.fixture
def mock_settings():
    settings = MagicMock()
    settings.llm.provider = "ollama"
    return settings


@pytest.fixture
def detector(mock_settings):
    return LlmPiiDetector(settings=mock_settings)


class TestLlmPiiDetector:
    def test_skips_on_mock_provider(self):
        settings = MagicMock()
        settings.llm.provider = "mock"
        det = LlmPiiDetector(settings=settings)
        result = det.detect("my SSN is nine one two thirty four five six seven eight")
        assert result == []

    def test_builds_residual_correctly(self):
        text = "Hello test@example.com world"
        spans = [(6, 22)]  # "test@example.com" span
        residual = LlmPiiDetector._build_residual(text, spans)
        # Span [6..22) → 16 chars replaced with spaces
        assert residual[6:22] == " " * 16
        assert "test@example.com" not in residual
        assert residual.startswith("Hello ")
        assert residual.endswith(" world")

    def test_parses_valid_json_response(self, detector):
        response = json.dumps(
            [
                {
                    "value": "912345678",
                    "raw": "nine one two three four five six seven eight",
                    "type": "ssn",
                }
            ]
        )
        text = "my social is nine one two three four five six seven eight"
        matches = detector._parse_response(response, text)
        assert len(matches) == 1
        assert matches[0].prefix == "TIN"
        assert matches[0].value == "912345678"
        assert matches[0].detector == "llm"

    def test_parses_json_with_markdown_fences(self, detector):
        response = '```json\n[{"value": "+15551234567", "raw": "five five five 123 4567", "type": "phone"}]\n```'
        matches = detector._parse_response(response, "call five five five 123 4567")
        assert len(matches) == 1
        assert matches[0].prefix == "PHN"

    def test_handles_non_json_response(self, detector):
        matches = detector._parse_response("I don't know what PII is", "some text")
        assert matches == []

    def test_handles_empty_array(self, detector):
        matches = detector._parse_response("[]", "no PII here")
        assert matches == []

    def test_handles_unknown_type(self, detector):
        response = json.dumps([{"value": "foo", "raw": "foo", "type": "unknown_type"}])
        matches = detector._parse_response(response, "foo")
        assert matches == []

    def test_detect_calls_llm_and_returns_matches(self, detector):
        llm_response = json.dumps(
            [{"value": "123456789", "raw": "one two three four five six seven eight nine", "type": "ssn"}]
        )
        mock_client = MagicMock()
        mock_client.generate.return_value = llm_response
        detector._llm_client = mock_client

        text = "my SSN is one two three four five six seven eight nine"
        matches = detector.detect(text, already_detected_spans=[])

        assert len(matches) == 1
        assert matches[0].prefix == "TIN"
        mock_client.generate.assert_called_once()

    def test_detect_handles_llm_failure(self, detector):
        mock_client = MagicMock()
        mock_client.generate.side_effect = RuntimeError("LLM down")
        detector._llm_client = mock_client

        result = detector.detect("some text with PII", already_detected_spans=[])
        assert result == []

    def test_circuit_breaker_trips_on_failure(self, detector):
        """After one LLM failure the breaker trips and subsequent calls skip."""
        mock_client = MagicMock()
        mock_client.generate.side_effect = RuntimeError("LLM down")
        detector._llm_client = mock_client

        # First call should trip the breaker
        detector.detect("text one", already_detected_spans=[])

        # Second call should return [] without hitting the client again
        mock_client.generate.reset_mock()
        result = detector.detect("text two", already_detected_spans=[])
        assert result == []
        mock_client.generate.assert_not_called()

    def test_all_type_mappings(self, detector):
        """Verify all supported PII types map to a valid prefix."""
        for pii_type, prefix in LlmPiiDetector._TYPE_TO_PREFIX.items():
            assert len(prefix) == 3, f"Prefix for {pii_type} should be 3 chars"
