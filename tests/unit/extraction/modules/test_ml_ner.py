"""Tests for i4g.extraction.modules.ml_ner — ML NER extraction module."""

from __future__ import annotations

from i4g.extraction.modules.ml_ner import MLNERModule
from i4g.extraction.types import ModuleProtocol, ScoredEntity


def _mock_predict(text: str) -> list[dict]:
    """Simulated ML NER prediction response."""
    return [
        {"entity_type": "PERSON", "value": "John Doe", "confidence": 0.92, "start": 0, "end": 8},
        {"entity_type": "ORG", "value": "TrustWallet", "confidence": 0.85, "start": 20, "end": 31},
        {"entity_type": "CRYPTO_WALLET", "value": "0xAbC123", "confidence": 0.95, "start": 40, "end": 48},
    ]


def _failing_predict(text: str) -> list[dict]:
    raise RuntimeError("ML endpoint unavailable")


class TestMLNERModuleProtocol:
    def test_implements_protocol(self):
        m = MLNERModule()
        assert isinstance(m, ModuleProtocol)

    def test_name(self):
        assert MLNERModule().name == "ml_ner"

    def test_authority_keys(self):
        auth = MLNERModule().authority
        assert auth["person"] == 0.7
        assert auth["organization"] == 0.7
        assert auth["wallet_address"] == 0.6


class TestMLNERModuleExtract:
    def test_disabled_when_no_predict_fn(self):
        m = MLNERModule(predict_fn=None)
        assert m.extract("John Doe from TrustWallet") == []

    def test_extracts_from_predictions(self):
        m = MLNERModule(predict_fn=_mock_predict)
        entities = m.extract("John Doe from TrustWallet sent 0xAbC123")
        assert len(entities) == 3

        persons = [e for e in entities if e.entity_type == "person"]
        assert len(persons) == 1
        assert persons[0].value == "John Doe"
        assert persons[0].confidence == 0.92
        assert persons[0].source_module == "ml_ner"
        assert persons[0].span == (0, 8)

        orgs = [e for e in entities if e.entity_type == "organization"]
        assert len(orgs) == 1

        wallets = [e for e in entities if e.entity_type == "wallet_address"]
        assert len(wallets) == 1

    def test_passes_through_model_confidence(self):
        m = MLNERModule(predict_fn=_mock_predict)
        entities = m.extract("some text")
        # Confidence should come from the model, not be hard-coded
        assert entities[0].confidence == 0.92
        assert entities[1].confidence == 0.85
        assert entities[2].confidence == 0.95

    def test_handles_prediction_failure(self):
        m = MLNERModule(predict_fn=_failing_predict)
        entities = m.extract("some text")
        assert entities == []

    def test_handles_non_list_response(self):
        m = MLNERModule(predict_fn=lambda text: "not a list")  # type: ignore[arg-type]
        entities = m.extract("some text")
        assert entities == []

    def test_handles_non_dict_items(self):
        m = MLNERModule(predict_fn=lambda text: ["not_a_dict", 42])
        entities = m.extract("some text")
        assert entities == []

    def test_skips_empty_values(self):
        m = MLNERModule(predict_fn=lambda text: [{"entity_type": "PERSON", "value": "", "confidence": 0.9}])
        entities = m.extract("some text")
        assert entities == []

    def test_all_results_are_scored_entities(self):
        m = MLNERModule(predict_fn=_mock_predict)
        entities = m.extract("some text")
        for e in entities:
            assert isinstance(e, ScoredEntity)
            assert e.source_module == "ml_ner"

    def test_type_mapping(self):
        def predict(text: str) -> list[dict]:
            return [
                {"entity_type": "PER", "value": "Alice", "confidence": 0.8},
                {"entity_type": "LOC", "value": "New York", "confidence": 0.7},
            ]

        m = MLNERModule(predict_fn=predict)
        entities = m.extract("some text")
        types = {e.entity_type for e in entities}
        assert "person" in types
        assert "location" in types
