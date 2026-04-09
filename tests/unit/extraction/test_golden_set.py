"""Golden test set — entity extraction quality harness.

Runs rule-based extraction on 20 hand-labeled scam texts and computes
per-type precision, recall, and F1.  Used for CI regression detection.

Run::

    pytest tests/unit/extraction/test_golden_set.py -v
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pytest

from i4g.extraction.ner_rules import extract_entities
from i4g.utils.entity_types import normalize_entity_type, normalize_entity_value

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "entity_extraction"
GOLDEN_SET_PATH = FIXTURES / "golden_test_set.json"

# Minimum F1 per entity type — CI gate (rule-based only, no LLM).
# Phone precision is limited without semantic context — accounts/routing numbers
# match phone patterns. URL precision limited by bare-domain extraction overlap.
MIN_F1: dict[str, float] = {
    "wallet_address": 0.6,
    "email_address": 0.8,
    "phone_number": 0.5,
    "url": 0.4,
    "social_handle": 0.5,
}


def _load_golden_set() -> list[dict]:
    with open(GOLDEN_SET_PATH) as f:
        return json.load(f)


def _flatten_extracted(raw: dict[str, list[str]]) -> dict[str, set[str]]:
    """Normalize extraction output to ``{canonical_type: {normalized_values}}``."""
    result: dict[str, set[str]] = defaultdict(set)
    for key, values in raw.items():
        ctype = normalize_entity_type(key)
        for v in values:
            result[ctype].add(normalize_entity_value(ctype, v))
    return dict(result)


def _flatten_expected(expected: dict[str, list[str]]) -> dict[str, set[str]]:
    """Normalize expected values the same way extraction is normalized."""
    result: dict[str, set[str]] = defaultdict(set)
    for ctype, values in expected.items():
        for v in values:
            result[ctype].add(normalize_entity_value(ctype, v))
    return dict(result)


class _Metrics:
    """Accumulator for precision/recall/F1 per entity type."""

    def __init__(self) -> None:
        self.tp: dict[str, int] = defaultdict(int)
        self.fp: dict[str, int] = defaultdict(int)
        self.fn: dict[str, int] = defaultdict(int)

    def update(self, etype: str, predicted: set[str], expected: set[str]) -> None:
        tp = predicted & expected
        fp = predicted - expected
        fn = expected - predicted
        self.tp[etype] += len(tp)
        self.fp[etype] += len(fp)
        self.fn[etype] += len(fn)

    def precision(self, etype: str) -> float:
        denom = self.tp[etype] + self.fp[etype]
        return self.tp[etype] / denom if denom else 0.0

    def recall(self, etype: str) -> float:
        denom = self.tp[etype] + self.fn[etype]
        return self.tp[etype] / denom if denom else 0.0

    def f1(self, etype: str) -> float:
        p = self.precision(etype)
        r = self.recall(etype)
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def types(self) -> set[str]:
        return set(self.tp) | set(self.fp) | set(self.fn)

    def summary(self) -> dict[str, dict[str, float]]:
        return {
            t: {"precision": self.precision(t), "recall": self.recall(t), "f1": self.f1(t)}
            for t in sorted(self.types())
        }


@pytest.fixture(scope="module")
def golden_results() -> tuple[_Metrics, list[dict]]:
    """Run extraction on the entire golden set and collect metrics."""
    cases = _load_golden_set()
    metrics = _Metrics()
    details: list[dict] = []

    for case in cases:
        raw = extract_entities(case["text"])
        predicted = _flatten_extracted(raw)
        expected = _flatten_expected(case.get("expected", {}))

        all_types = set(predicted) | set(expected)
        for etype in all_types:
            pred_vals = predicted.get(etype, set())
            exp_vals = expected.get(etype, set())
            metrics.update(etype, pred_vals, exp_vals)

        details.append(
            {
                "id": case["id"],
                "predicted": {k: sorted(v) for k, v in predicted.items()},
                "expected": {k: sorted(v) for k, v in expected.items()},
            }
        )

    return metrics, details


def test_golden_set_overall_quality(golden_results: tuple[_Metrics, list[dict]]) -> None:
    """Report overall extraction quality — always passes, used for visibility."""
    metrics, _ = golden_results
    summary = metrics.summary()
    print("\n=== Entity Extraction Quality Report ===")
    for etype, scores in summary.items():
        print(f"  {etype:20s}  P={scores['precision']:.2f}  R={scores['recall']:.2f}  F1={scores['f1']:.2f}")


@pytest.mark.parametrize("entity_type,min_f1", list(MIN_F1.items()))
def test_golden_set_min_f1(
    golden_results: tuple[_Metrics, list[dict]],
    entity_type: str,
    min_f1: float,
) -> None:
    """Fail if any gated entity type drops below minimum F1."""
    metrics, _ = golden_results
    actual_f1 = metrics.f1(entity_type)
    assert actual_f1 >= min_f1, (
        f"{entity_type} F1={actual_f1:.3f} below minimum {min_f1:.2f}. "
        f"P={metrics.precision(entity_type):.3f} R={metrics.recall(entity_type):.3f}"
    )


def test_golden_set_no_entities_case(golden_results: tuple[_Metrics, list[dict]]) -> None:
    """The 'no entities' test case should extract nothing of significance."""
    _, details = golden_results
    no_entity_case = next((d for d in details if d["id"] == "no_entities_01"), None)
    assert no_entity_case is not None, "Missing no_entities_01 test case"
    # Allow crypto_token noise (keyword detection) but no threat entities
    threat_types = {
        "wallet_address",
        "bank_account",
        "payment_handle",
        "email_address",
        "phone_number",
        "url",
        "domain",
    }
    for etype, vals in no_entity_case["predicted"].items():
        if etype in threat_types:
            assert not vals, f"no_entities_01 should not produce {etype}: {vals}"
