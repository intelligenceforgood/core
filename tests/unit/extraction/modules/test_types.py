"""Tests for i4g.extraction.types — core extraction type definitions."""

from __future__ import annotations

from i4g.extraction.types import (
    ConfidenceGate,
    ExtractionResult,
    MergeAction,
    MergeDecision,
    ModuleProtocol,
    ModuleReport,
    ModuleStatus,
    ScoredEntity,
)


class TestScoredEntity:
    def test_creation(self):
        e = ScoredEntity(
            entity_type="wallet_address",
            value="0xAbC123",
            canonical_value="0xabc123",
            confidence=0.9,
            source_module="regex",
        )
        assert e.entity_type == "wallet_address"
        assert e.value == "0xAbC123"
        assert e.canonical_value == "0xabc123"
        assert e.confidence == 0.9
        assert e.source_module == "regex"
        assert e.span is None

    def test_with_span(self):
        e = ScoredEntity(
            entity_type="person",
            value="John Doe",
            canonical_value="John Doe",
            confidence=0.7,
            source_module="llm",
            span=(10, 18),
        )
        assert e.span == (10, 18)

    def test_frozen(self):
        e = ScoredEntity(
            entity_type="person",
            value="Jane",
            canonical_value="Jane",
            confidence=0.5,
            source_module="heuristic",
        )
        import pytest

        with pytest.raises(AttributeError):
            e.confidence = 0.8  # type: ignore[misc]

    def test_hashable(self):
        e = ScoredEntity(
            entity_type="email_address",
            value="a@b.com",
            canonical_value="a@b.com",
            confidence=0.9,
            source_module="regex",
        )
        assert hash(e) is not None
        assert {e}  # Can be added to a set


class TestMergeDecision:
    def test_creation(self):
        d = MergeDecision(
            entity_type="person",
            value="Wells Fargo",
            action=MergeAction.DROPPED,
            reason="blocklisted",
            final_confidence=0.0,
            sources=("llm",),
        )
        assert d.action == MergeAction.DROPPED
        assert d.sources == ("llm",)


class TestModuleReport:
    def test_defaults(self):
        r = ModuleReport(module_name="regex")
        assert r.status == ModuleStatus.SUCCESS
        assert r.entity_count == 0
        assert r.elapsed_seconds == 0.0
        assert r.error is None

    def test_failed(self):
        r = ModuleReport(
            module_name="llm",
            status=ModuleStatus.FAILED,
            error="timeout",
        )
        assert r.status == ModuleStatus.FAILED
        assert r.error == "timeout"


class TestExtractionResult:
    def test_empty(self):
        r = ExtractionResult()
        assert r.entities == []
        assert r.module_reports == []
        assert r.merge_log == []
        assert r.quality_score is None


class TestConfidenceGate:
    def test_creation(self):
        g = ConfidenceGate(entity_type="person", threshold=0.6)
        assert g.entity_type == "person"
        assert g.threshold == 0.6


class TestModuleProtocol:
    def test_regex_module_satisfies_protocol(self):
        from i4g.extraction.modules.regex import RegexModule

        m = RegexModule()
        assert isinstance(m, ModuleProtocol)

    def test_heuristic_module_satisfies_protocol(self):
        from i4g.extraction.modules.heuristic import HeuristicModule

        m = HeuristicModule()
        assert isinstance(m, ModuleProtocol)

    def test_blocklist_module_satisfies_protocol(self):
        from i4g.extraction.modules.blocklist import BlocklistModule

        m = BlocklistModule()
        assert isinstance(m, ModuleProtocol)
