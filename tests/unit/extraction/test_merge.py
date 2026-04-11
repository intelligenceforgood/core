"""Tests for the merge engine — i4g.extraction.merge."""

from __future__ import annotations

from i4g.extraction.merge import merge_entities
from i4g.extraction.modules.blocklist import BlocklistModule
from i4g.extraction.types import (
    MergeAction,
    ModuleReport,
    ModuleStatus,
    ScoredEntity,
)

# ---------------------------------------------------------------------------
# Helpers — lightweight stubs implementing ModuleProtocol
# ---------------------------------------------------------------------------


class _StubModule:
    """Minimal module stub for merge tests."""

    def __init__(self, name: str, authority: dict[str, float]) -> None:
        self._name = name
        self._authority = authority

    @property
    def name(self) -> str:
        return self._name

    @property
    def authority(self) -> dict[str, float]:
        return self._authority

    def extract(self, text: str) -> list[ScoredEntity]:
        return []


def _entity(entity_type: str, value: str, confidence: float, source: str) -> ScoredEntity:
    return ScoredEntity(
        entity_type=entity_type,
        value=value,
        canonical_value=value.lower(),
        confidence=confidence,
        source_module=source,
    )


def _report(name: str, status: ModuleStatus = ModuleStatus.SUCCESS) -> ModuleReport:
    return ModuleReport(module_name=name, status=status, entity_count=0)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAuthorityWeightedConfidence:
    """Test that final confidence = authority * raw confidence."""

    def test_single_source_authority_applied(self):
        regex = _StubModule("regex", {"wallet_address": 1.0})
        candidates = [_entity("wallet_address", "0xABC", 0.9, "regex")]
        reports = [_report("regex")]

        merged, log = merge_entities(
            candidates,
            modules=[regex],
            module_reports=reports,
            confidence_gates={"wallet_address": 0.0},
        )
        assert len(merged) == 1
        # 1.0 * 0.9 = 0.9
        assert merged[0].confidence == 0.9

    def test_low_authority_reduces_confidence(self):
        heuristic = _StubModule("heuristic", {"person": 0.4})
        candidates = [_entity("person", "John Doe", 0.5, "heuristic")]
        reports = [_report("heuristic")]

        merged, log = merge_entities(
            candidates,
            modules=[heuristic],
            module_reports=reports,
            confidence_gates={"person": 0.0},
        )
        assert len(merged) == 1
        # 0.4 * 0.5 = 0.2
        assert merged[0].confidence == 0.2


class TestMultiSourceAgreement:
    """When multiple modules find the same entity, confidence is boosted."""

    def test_two_sources_bonus(self):
        regex = _StubModule("regex", {"wallet_address": 1.0})
        llm = _StubModule("llm", {"wallet_address": 0.7})
        candidates = [
            _entity("wallet_address", "0xABC", 0.9, "regex"),
            _entity("wallet_address", "0xABC", 0.7, "llm"),
        ]
        reports = [_report("regex"), _report("llm")]

        merged, log = merge_entities(
            candidates,
            modules=[regex, llm],
            module_reports=reports,
            confidence_gates={"wallet_address": 0.0},
        )
        assert len(merged) == 1
        # max(1.0*0.9, 0.7*0.7) = 0.9, + 0.1*(2-1) = 1.0
        assert merged[0].confidence == 1.0

    def test_three_sources_bonus(self):
        m1 = _StubModule("regex", {"email_address": 1.0})
        m2 = _StubModule("llm", {"email_address": 0.7})
        m3 = _StubModule("ml_ner", {"email_address": 0.6})
        candidates = [
            _entity("email_address", "a@b.com", 0.9, "regex"),
            _entity("email_address", "a@b.com", 0.7, "llm"),
            _entity("email_address", "a@b.com", 0.6, "ml_ner"),
        ]
        reports = [_report("regex"), _report("llm"), _report("ml_ner")]

        merged, _ = merge_entities(
            candidates,
            modules=[m1, m2, m3],
            module_reports=reports,
            confidence_gates={"email_address": 0.0},
        )
        assert len(merged) == 1
        # max(1.0*0.9, 0.7*0.7, 0.6*0.6) = 0.9, + 0.1*2 = 1.0 (clamped)
        assert merged[0].confidence == 1.0

    def test_boosted_action_in_merge_log(self):
        regex = _StubModule("regex", {"wallet_address": 1.0})
        llm = _StubModule("llm", {"wallet_address": 0.7})
        candidates = [
            _entity("wallet_address", "0xABC", 0.9, "regex"),
            _entity("wallet_address", "0xABC", 0.7, "llm"),
        ]
        reports = [_report("regex"), _report("llm")]

        _, log = merge_entities(
            candidates,
            modules=[regex, llm],
            module_reports=reports,
            confidence_gates={"wallet_address": 0.0},
        )
        assert len(log) == 1
        assert log[0].action == MergeAction.BOOSTED
        assert "llm" in log[0].sources
        assert "regex" in log[0].sources


class TestContradictionPenalty:
    """When a high-authority module ran but didn't find the entity."""

    def test_penalty_when_high_authority_module_disagrees(self):
        heuristic = _StubModule("heuristic", {"person": 0.4})
        llm = _StubModule("llm", {"person": 0.8})  # High authority, didn't find entity
        candidates = [_entity("person", "John Doe", 0.5, "heuristic")]
        reports = [_report("heuristic"), _report("llm")]

        merged, _ = merge_entities(
            candidates,
            modules=[heuristic, llm],
            module_reports=reports,
            confidence_gates={"person": 0.0},
        )
        assert len(merged) == 1
        # 0.4 * 0.5 = 0.2, then * 0.8 (contradiction) = 0.16
        assert merged[0].confidence == 0.16

    def test_no_penalty_when_module_failed(self):
        """Failed modules should not penalize — they didn't actually look."""
        heuristic = _StubModule("heuristic", {"person": 0.4})
        llm = _StubModule("llm", {"person": 0.8})
        candidates = [_entity("person", "John Doe", 0.5, "heuristic")]
        # LLM failed — should not penalize
        reports = [_report("heuristic"), _report("llm", ModuleStatus.FAILED)]

        merged, _ = merge_entities(
            candidates,
            modules=[heuristic, llm],
            module_reports=reports,
            confidence_gates={"person": 0.0},
        )
        assert len(merged) == 1
        # No contradiction penalty: 0.4 * 0.5 = 0.2
        assert merged[0].confidence == 0.2


class TestConfidenceGating:
    """Entities below the gate threshold are dropped."""

    def test_entity_below_gate_dropped(self):
        heuristic = _StubModule("heuristic", {"person": 0.4})
        candidates = [_entity("person", "John Doe", 0.5, "heuristic")]
        reports = [_report("heuristic")]

        merged, log = merge_entities(
            candidates,
            modules=[heuristic],
            module_reports=reports,
            confidence_gates={"person": 0.6},
        )
        assert len(merged) == 0
        assert len(log) == 1
        assert log[0].action == MergeAction.DROPPED
        assert "below_gate" in log[0].reason

    def test_entity_above_gate_kept(self):
        regex = _StubModule("regex", {"email_address": 1.0})
        candidates = [_entity("email_address", "test@test.com", 0.9, "regex")]
        reports = [_report("regex")]

        merged, _ = merge_entities(
            candidates,
            modules=[regex],
            module_reports=reports,
            confidence_gates={"email_address": 0.5},
        )
        assert len(merged) == 1

    def test_default_gate_when_type_not_in_gates(self):
        """Types not in the gates dict use the default threshold of 0.5."""
        regex = _StubModule("regex", {"unknown_type": 1.0})
        candidates = [_entity("unknown_type", "xyz", 0.6, "regex")]
        reports = [_report("regex")]

        merged, _ = merge_entities(
            candidates,
            modules=[regex],
            module_reports=reports,
            confidence_gates={},
        )
        # 1.0 * 0.6 = 0.6 >= 0.5 default gate
        assert len(merged) == 1


class TestBlocklistFiltering:
    """Blocklisted values are dropped even if above the gate."""

    def test_blocklisted_person_dropped(self):
        llm = _StubModule("llm", {"person": 0.8})
        candidates = [_entity("person", "Wells Fargo", 0.7, "llm")]
        reports = [_report("llm")]
        blocklist = BlocklistModule()

        merged, log = merge_entities(
            candidates,
            modules=[llm],
            module_reports=reports,
            confidence_gates={"person": 0.0},
            blocklist=blocklist,
        )
        assert len(merged) == 0
        assert len(log) == 1
        assert log[0].action == MergeAction.DROPPED
        assert "blocklisted" in log[0].reason

    def test_non_blocklisted_person_kept(self):
        llm = _StubModule("llm", {"person": 0.8})
        candidates = [_entity("person", "Satoshi Nakamoto", 0.7, "llm")]
        reports = [_report("llm")]
        blocklist = BlocklistModule()

        merged, _ = merge_entities(
            candidates,
            modules=[llm],
            module_reports=reports,
            confidence_gates={"person": 0.0},
            blocklist=blocklist,
        )
        assert len(merged) == 1


class TestDeduplication:
    """Entities with same (type, canonical_value) from different modules are merged."""

    def test_dedup_same_canonical(self):
        regex = _StubModule("regex", {"email_address": 1.0})
        llm = _StubModule("llm", {"email_address": 0.7})
        candidates = [
            _entity("email_address", "A@B.COM", 0.9, "regex"),
            _entity("email_address", "a@b.com", 0.7, "llm"),
        ]
        reports = [_report("regex"), _report("llm")]

        merged, _ = merge_entities(
            candidates,
            modules=[regex, llm],
            module_reports=reports,
            confidence_gates={"email_address": 0.0},
        )
        assert len(merged) == 1


class TestMergeLogControl:
    """include_merge_log=False skips log construction."""

    def test_no_log_when_disabled(self):
        regex = _StubModule("regex", {"wallet_address": 1.0})
        candidates = [_entity("wallet_address", "0xABC", 0.9, "regex")]
        reports = [_report("regex")]

        merged, log = merge_entities(
            candidates,
            modules=[regex],
            module_reports=reports,
            confidence_gates={"wallet_address": 0.0},
            include_merge_log=False,
        )
        assert len(merged) == 1
        assert len(log) == 0


class TestEmptyInput:
    def test_no_candidates(self):
        merged, log = merge_entities(
            [],
            modules=[],
            module_reports=[],
            confidence_gates={},
        )
        assert merged == []
        assert log == []
