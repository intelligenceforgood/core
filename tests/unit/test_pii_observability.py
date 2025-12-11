"""Unit tests for PiiVaultObservability metrics helpers."""

from i4g.pii.observability import PiiVaultObservability


class StubObservability:
    def __init__(self) -> None:
        self.increments: list[tuple[str, float, dict]] = []
        self.events: list[tuple[str, dict]] = []

    def increment(self, metric: str, *, value: float, tags: dict | None = None) -> None:
        self.increments.append((metric, value, tags or {}))

    def emit_event(self, event: str, **fields) -> None:
        self.events.append((event, fields))


def test_record_tokenization_emits_metrics_and_event():
    obs = PiiVaultObservability(observability=StubObservability())

    obs.record_tokenization(
        token_count=3,
        field_count=2,
        raw_bytes=42,
        source="ocr",
        detector="detector_a",
        prefix="eml",
        case_id="case-123",
    )

    increments = {metric: (value, tags) for metric, value, tags in obs.observability.increments}
    assert increments["pii.tokenization.tokens"][0] == 3.0
    assert increments["pii.tokenization.fields"][0] == 2.0
    assert increments["pii.tokenization.bytes"][0] == 42.0
    assert increments["pii.tokenization.tokens"][1]["source"] == "ocr"

    event_names = [name for name, _ in obs.observability.events]
    assert "pii.tokenization.coverage" in event_names


def test_record_detector_confidence_buckets_and_logs():
    obs = PiiVaultObservability(observability=StubObservability())

    obs.record_detector_confidence(
        detector="detector_a",
        prefix="ssn",
        confidence=0.65,
        verdict="accepted",
        case_id="case-123",
    )

    increments = obs.observability.increments
    assert increments
    metric, value, tags = increments[0]
    assert metric == "pii.detector.confidence"
    assert value == 1.0
    assert tags["bucket"] == "medium"
    assert tags["verdict"] == "accepted"

    event = obs.observability.events[0]
    assert event[0] == "pii.detector.decision"
    assert event[1]["confidence"] == 0.65


def test_record_detokenization_attempt_emits_metrics_and_event():
    obs = PiiVaultObservability(observability=StubObservability())

    obs.record_detokenization_attempt(
        actor="svc-app",
        prefix="eid",
        outcome="denied",
        reason="missing_approval",
        case_id="case-123",
    )

    increments = obs.observability.increments
    assert increments
    metric, value, tags = increments[0]
    assert metric == "pii.detokenization.attempt"
    assert value == 1.0
    assert tags["actor"] == "svc-app"
    assert tags["outcome"] == "denied"
    assert tags["prefix"] == "eid"

    event = obs.observability.events[0]
    assert event[0] == "pii.detokenization.attempt"
    assert event[1]["reason"] == "missing_approval"
    assert event[1]["case_id"] == "case-123"


def test_alert_unusual_access_emits_alert_metric_and_event():
    obs = PiiVaultObservability(observability=StubObservability())

    obs.alert_unusual_access(
        actor="svc-app",
        prefix="ssn",
        reason="after_hours",
        severity="critical",
        case_id="case-999",
    )

    increments = obs.observability.increments
    assert increments
    metric, value, tags = increments[0]
    assert metric == "pii.detokenization.alert"
    assert value == 1.0
    assert tags["actor"] == "svc-app"
    assert tags["prefix"] == "ssn"
    assert tags["severity"] == "critical"

    event = obs.observability.events[0]
    assert event[0] == "pii.detokenization.alert"
    assert event[1]["reason"] == "after_hours"
    assert event[1]["case_id"] == "case-999"
