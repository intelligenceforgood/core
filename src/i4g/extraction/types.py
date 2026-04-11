"""Core types for the entity extraction pipeline.

All extraction modules produce ``ScoredEntity`` instances.  The orchestrator
collects them, runs the merge engine, and returns an ``ExtractionResult``
containing the final entities plus full provenance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# ScoredEntity — the atomic unit of extraction output
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ScoredEntity:
    """A single entity extracted by a module, with source and confidence."""

    entity_type: str
    """Canonical entity type (e.g. ``"wallet_address"``, ``"person"``)."""

    value: str
    """Raw extracted value."""

    canonical_value: str
    """Normalized value (lowercase hex for wallets, title-case for names, etc.)."""

    confidence: float
    """Module-assigned confidence in ``[0, 1]``."""

    source_module: str
    """Name of the module that produced this entity."""

    span: tuple[int, int] | None = None
    """Character offsets ``(start, end)`` in the source text, if available."""


# ---------------------------------------------------------------------------
# MergeDecision — audit record for the merge engine
# ---------------------------------------------------------------------------


class MergeAction(StrEnum):
    """Possible outcomes for a candidate entity during the merge phase."""

    KEPT = "kept"
    DROPPED = "dropped"
    BOOSTED = "boosted"


@dataclass(frozen=True, slots=True)
class MergeDecision:
    """Audit trail entry — one per candidate entity processed by the merge engine."""

    entity_type: str
    value: str
    action: MergeAction
    reason: str
    final_confidence: float
    sources: tuple[str, ...] = ()
    """Modules that produced this entity."""


# ---------------------------------------------------------------------------
# ModuleReport — per-module execution summary
# ---------------------------------------------------------------------------


class ModuleStatus(StrEnum):
    """Outcome of running a single extraction module."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(slots=True)
class ModuleReport:
    """Execution report for a single extraction module."""

    module_name: str
    status: ModuleStatus = ModuleStatus.SUCCESS
    entity_count: int = 0
    elapsed_seconds: float = 0.0
    error: str | None = None


# ---------------------------------------------------------------------------
# ExtractionResult — the top-level return value
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ExtractionResult:
    """Complete result of running the extraction pipeline on a single text."""

    entities: list[ScoredEntity] = field(default_factory=list)
    module_reports: list[ModuleReport] = field(default_factory=list)
    merge_log: list[MergeDecision] = field(default_factory=list)
    quality_score: float | None = None


# ---------------------------------------------------------------------------
# ConfidenceGate — per-type minimum confidence threshold
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConfidenceGate:
    """Minimum confidence required for an entity type to survive the merge."""

    entity_type: str
    threshold: float


# ---------------------------------------------------------------------------
# ModuleProtocol — interface that every extraction module must implement
# ---------------------------------------------------------------------------


@runtime_checkable
class ModuleProtocol(Protocol):
    """Interface for extraction modules.

    Every module declares a ``name``, an ``authority`` mapping from entity type
    to authority weight, and an ``extract`` method.
    """

    @property
    def name(self) -> str:
        """Unique module identifier (e.g. ``"regex"``, ``"llm"``)."""
        ...

    @property
    def authority(self) -> dict[str, float]:
        """Per-entity-type authority weight in ``[0, 1]``.

        Higher authority means this module's opinion carries more weight in
        the merge engine.  A module that doesn't handle a given type should
        omit it from the dict.
        """
        ...

    def extract(self, text: str) -> list[ScoredEntity]:
        """Run extraction on *text* and return scored entities."""
        ...
