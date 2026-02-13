"""Regression tests for classification system against golden examples.

Validates that:
- Golden dataset JSON loads correctly and has sufficient coverage.
- The risk scoring formula produces non-zero scores when risk_weights are present.
- FraudClassificationResult round-trips through golden examples.
- Taxonomy definitions include risk_weight on all weighted categories.
"""

import json
import yaml
import pytest

from i4g.settings import PROJECT_ROOT
from i4g.taxonomy.models import FraudClassificationResult, ScoredLabel
from i4g.services.classifier import FraudClassifier, MockLLMClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

GOLDEN_PATH = PROJECT_ROOT / "src" / "i4g" / "taxonomy" / "golden_examples.json"
DEFINITIONS_PATH = PROJECT_ROOT / "src" / "i4g" / "taxonomy" / "definitions.yaml"


@pytest.fixture(scope="module")
def golden_examples() -> list[dict]:
    """Load golden examples from disk."""
    with open(GOLDEN_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def definitions() -> dict:
    """Load taxonomy definitions from disk."""
    with open(DEFINITIONS_PATH) as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def classifier() -> FraudClassifier:
    """Create a FraudClassifier with mock LLM (only used for structure tests)."""
    return FraudClassifier(llm_client=MockLLMClient())


# ---------------------------------------------------------------------------
# Golden dataset health
# ---------------------------------------------------------------------------


class TestGoldenDatasetHealth:
    """Ensure the golden examples file is well-formed and sufficient."""

    def test_minimum_example_count(self, golden_examples: list[dict]):
        """F18: Require at least 10 golden examples."""
        assert len(golden_examples) >= 10, f"Need ≥10 golden examples, found {len(golden_examples)}"

    def test_all_examples_have_required_keys(self, golden_examples: list[dict]):
        """Each golden example must contain input text and output classification."""
        for i, ex in enumerate(golden_examples):
            assert "input" in ex, f"Example {i} missing 'input'"
            assert "output" in ex, f"Example {i} missing 'output'"
            assert len(ex["input"]) > 10, f"Example {i} input too short"

    def test_output_structure_matches_model(self, golden_examples: list[dict]):
        """Each output must parse as a valid FraudClassificationResult."""
        for i, ex in enumerate(golden_examples):
            try:
                result = FraudClassificationResult(**ex["output"])
            except Exception as e:
                pytest.fail(f"Example {i} output invalid: {e}")
            assert len(result.intent) > 0, f"Example {i} has no intent labels"

    def test_intent_coverage(self, golden_examples: list[dict]):
        """Golden examples should cover all 9 intent types."""
        covered_intents: set[str] = set()
        for ex in golden_examples:
            for intent_item in ex["output"].get("intent", []):
                covered_intents.add(intent_item["label"])

        expected = {
            "INTENT.IMPOSTER",
            "INTENT.INVESTMENT",
            "INTENT.ROMANCE",
            "INTENT.PRIZE",
            "INTENT.TECH_SUPPORT",
            "INTENT.EMPLOYMENT",
            "INTENT.EXTORTION",
            "INTENT.SHOPPING",
            "INTENT.CHARITY",
        }
        missing = expected - covered_intents
        assert not missing, f"Golden examples missing intent coverage for: {missing}"

    def test_risk_scores_are_set(self, golden_examples: list[dict]):
        """Each golden example should have a non-zero risk_score."""
        for i, ex in enumerate(golden_examples):
            score = ex["output"].get("risk_score", 0)
            assert score > 0, f"Example {i} has risk_score={score}, expected > 0"


# ---------------------------------------------------------------------------
# Taxonomy definitions health
# ---------------------------------------------------------------------------


class TestTaxonomyDefinitionsHealth:
    """Validate risk_weight presence in definitions.yaml."""

    @pytest.mark.parametrize("category", ["intents", "techniques", "actions"])
    def test_risk_weights_present(self, definitions: dict, category: str):
        """Every item in weighted categories must have a risk_weight > 0."""
        items = definitions.get(category, [])
        assert len(items) > 0, f"Category '{category}' is empty"
        for item in items:
            code = item.get("code", "<unknown>")
            weight = item.get("risk_weight")
            assert weight is not None, f"{code} missing risk_weight"
            assert weight > 0, f"{code} risk_weight must be > 0, got {weight}"

    def test_risk_weights_in_valid_range(self, definitions: dict):
        """Risk weights should be between 1 and 10 (inclusive)."""
        for category in ["intents", "techniques", "actions"]:
            for item in definitions.get(category, []):
                code = item.get("code", "<unknown>")
                weight = item.get("risk_weight", 0)
                assert 1 <= weight <= 10, f"{code} risk_weight={weight} not in [1, 10]"


# ---------------------------------------------------------------------------
# Risk scoring regression
# ---------------------------------------------------------------------------


class TestRiskScoringRegression:
    """Validate the risk scoring formula returns meaningful values."""

    def test_mock_classification_nonzero_score(self, classifier: FraudClassifier):
        """Mock classifier should return non-zero risk_score now that risk_weights exist."""
        result = classifier.classify("Suspicious text for testing")
        assert result.risk_score > 0.0, (
            f"Expected non-zero risk_score with risk_weights populated, got {result.risk_score}"
        )

    def test_risk_score_within_bounds(self, classifier: FraudClassifier):
        """Risk score must be in [0, 100]."""
        result = classifier.classify("Test input")
        assert 0.0 <= result.risk_score <= 100.0

    def test_higher_weights_yield_higher_scores(self, classifier: FraudClassifier):
        """Manual construction: result with high-weight labels should score higher."""
        # High-risk: Extortion (10) + Fear (9) + Send Money (9)
        high_risk = FraudClassificationResult(
            intent=[ScoredLabel(label="INTENT.EXTORTION", confidence=0.95, explanation="test")],
            techniques=[ScoredLabel(label="SE.FEAR", confidence=0.9, explanation="test")],
            actions=[ScoredLabel(label="ACTION.SEND_MONEY", confidence=0.9, explanation="test")],
        )
        high_score = classifier._calculate_risk_score(high_risk)

        # Low-risk: Shopping (5) + Reciprocity (4)
        low_risk = FraudClassificationResult(
            intent=[ScoredLabel(label="INTENT.SHOPPING", confidence=0.6, explanation="test")],
            techniques=[ScoredLabel(label="SE.RECIPROCITY", confidence=0.5, explanation="test")],
            actions=[],
        )
        low_score = classifier._calculate_risk_score(low_risk)

        assert high_score > low_score, f"High-risk ({high_score}) should exceed low-risk ({low_score})"
        assert high_score > 40.0, f"High-risk score {high_score} too low"
        assert low_score < 30.0, f"Low-risk score {low_score} too high"

    def test_score_caps_at_100(self, classifier: FraudClassifier):
        """Even with maximum weights, score should cap at 100."""
        extreme_result = FraudClassificationResult(
            intent=[ScoredLabel(label="INTENT.EXTORTION", confidence=1.0, explanation="test")],
            techniques=[
                ScoredLabel(label="SE.FEAR", confidence=1.0, explanation="test"),
                ScoredLabel(label="SE.URGENCY", confidence=1.0, explanation="test"),
                ScoredLabel(label="SE.AUTHORITY", confidence=1.0, explanation="test"),
            ],
            actions=[
                ScoredLabel(label="ACTION.SEND_MONEY", confidence=1.0, explanation="test"),
                ScoredLabel(label="ACTION.CRYPTO", confidence=1.0, explanation="test"),
                ScoredLabel(label="ACTION.GIFT_CARDS", confidence=1.0, explanation="test"),
            ],
        )
        score = classifier._calculate_risk_score(extreme_result)
        assert score == 100.0, f"Extreme case should cap at 100, got {score}"

    def test_risk_weight_map_populated(self, classifier: FraudClassifier):
        """The internal risk_weights dict should be populated from definitions.yaml."""
        assert len(classifier.risk_weights) > 0, "risk_weights map is empty"
        assert "INTENT.IMPOSTER" in classifier.risk_weights
        assert "SE.URGENCY" in classifier.risk_weights
        assert "ACTION.CLICK_LINK" in classifier.risk_weights


# ---------------------------------------------------------------------------
# Round-trip: golden output -> model -> dict
# ---------------------------------------------------------------------------


class TestGoldenRoundTrip:
    """Validate FraudClassificationResult model round-trips through golden data."""

    def test_all_golden_outputs_round_trip(self, golden_examples: list[dict]):
        """Parse each golden output into a model and back to dict, ensuring no data loss."""
        for i, ex in enumerate(golden_examples):
            model = FraudClassificationResult(**ex["output"])
            dumped = model.model_dump()

            # Verify key fields survive the round-trip
            assert len(dumped["intent"]) == len(ex["output"]["intent"]), f"Example {i}: intent count mismatch"
            assert dumped["risk_score"] == ex["output"]["risk_score"], f"Example {i}: risk_score mismatch"
            assert dumped["taxonomy_version"] == ex["output"]["taxonomy_version"], (
                f"Example {i}: taxonomy_version mismatch"
            )
