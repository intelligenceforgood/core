import pytest
from pydantic import ValidationError

from i4g.taxonomy.enums import DeliveryChannel, ScamIntent
from i4g.taxonomy.models import FraudClassificationResult, ScoredLabel


def test_valid_classification_result():
    result = FraudClassificationResult(
        intent=[ScoredLabel(label=ScamIntent.IMPOSTER.value, confidence=0.9)],
        channel=[ScoredLabel(label=DeliveryChannel.SMS.value, confidence=0.8)],
        taxonomy_version="1.0",
    )
    assert result.intent[0].label == "INTENT.IMPOSTER"
    assert result.intent[0].confidence == 0.9
    assert result.taxonomy_version == "1.0"


def test_invalid_intent_label():
    with pytest.raises(ValidationError) as excinfo:
        FraudClassificationResult(intent=[ScoredLabel(label="INVALID_LABEL", confidence=0.9)], taxonomy_version="1.0")
    assert "Invalid intent label" in str(excinfo.value)


def test_invalid_confidence_score():
    with pytest.raises(ValidationError) as excinfo:
        ScoredLabel(label=ScamIntent.IMPOSTER.value, confidence=1.5)
    assert "Input should be less than or equal to 1" in str(excinfo.value)

    with pytest.raises(ValidationError) as excinfo:
        ScoredLabel(label=ScamIntent.IMPOSTER.value, confidence=-0.1)
    assert "Input should be greater than or equal to 0" in str(excinfo.value)


def test_empty_lists_are_allowed():
    result = FraudClassificationResult(taxonomy_version="1.0")
    assert result.intent == []
    assert result.channel == []


def test_multiple_labels():
    result = FraudClassificationResult(
        intent=[
            ScoredLabel(label=ScamIntent.IMPOSTER.value, confidence=0.8),
            ScoredLabel(label=ScamIntent.ROMANCE.value, confidence=0.5),
        ],
        taxonomy_version="1.0",
    )
    assert len(result.intent) == 2
