"""Authority-ranked merge engine for extraction results.

Groups ``ScoredEntity`` instances by ``(entity_type, canonical_value)``, applies
authority-weighted confidence scoring, multi-source agreement bonuses,
contradiction penalties, confidence gating, and blocklist filtering.

Every merge decision is recorded as a ``MergeDecision`` for audit.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from i4g.extraction.modules.blocklist import BlocklistModule
from i4g.extraction.types import (
    MergeAction,
    MergeDecision,
    ModuleProtocol,
    ModuleReport,
    ModuleStatus,
    ScoredEntity,
)

logger = logging.getLogger(__name__)

# Bonus added per additional agreeing source beyond the first.
_AGREEMENT_BONUS = 0.1

# Multiplicative penalty when a high-authority module didn't find a value.
_CONTRADICTION_FACTOR = 0.8

# A module is considered "high authority" for a type at or above this threshold.
_HIGH_AUTHORITY_THRESHOLD = 0.7

# Default confidence gate when no explicit gate is configured for a type.
_DEFAULT_GATE = 0.5


def merge_entities(
    candidates: list[ScoredEntity],
    *,
    modules: list[ModuleProtocol],
    module_reports: list[ModuleReport],
    confidence_gates: dict[str, float] | None = None,
    blocklist: BlocklistModule | None = None,
    include_merge_log: bool = True,
) -> tuple[list[ScoredEntity], list[MergeDecision]]:
    """Run the authority-ranked merge algorithm.

    Args:
        candidates: All ``ScoredEntity`` instances from all modules.
        modules: The full list of registered modules (needed for
            contradiction penalty).
        module_reports: Execution reports — only modules with
            ``status != FAILED`` are considered for contradiction checks.
        confidence_gates: ``{entity_type: threshold}`` map. If ``None``,
            a permissive default of 0.5 is used for all types.
        blocklist: Optional ``BlocklistModule`` for false-positive filtering.
        include_merge_log: When ``False``, skip ``MergeDecision`` construction
            for performance in production batch jobs.

    Returns:
        ``(merged_entities, merge_log)`` tuple.
    """
    gates = confidence_gates or {}

    # Names of modules that ran successfully (for contradiction penalty).
    successful_modules: set[str] = set()
    for report in module_reports:
        if report.status != ModuleStatus.FAILED:
            successful_modules.add(report.module_name)

    # Build authority lookup: module_name → {entity_type → authority}.
    authority_lookup: dict[str, dict[str, float]] = {}
    for mod in modules:
        authority_lookup[mod.name] = mod.authority

    # Group candidates by (entity_type, canonical_value).
    groups: dict[tuple[str, str], list[ScoredEntity]] = defaultdict(list)
    for ent in candidates:
        groups[(ent.entity_type, ent.canonical_value)].append(ent)

    merged: list[ScoredEntity] = []
    merge_log: list[MergeDecision] = []

    for (entity_type, canonical_value), group in groups.items():
        sources = tuple(sorted({e.source_module for e in group}))

        # 1. Authority-weighted confidence: max(authority * confidence) across sources.
        weighted = 0.0
        best_entity = group[0]
        for ent in group:
            mod_authority = authority_lookup.get(ent.source_module, {}).get(entity_type, 0.5)
            score = mod_authority * ent.confidence
            if score > weighted:
                weighted = score
                best_entity = ent

        # 2. Multi-source agreement bonus.
        if len(sources) > 1:
            weighted = min(1.0, weighted + _AGREEMENT_BONUS * (len(sources) - 1))

        # 3. Contradiction penalty — high-authority module ran but did NOT find this value.
        for mod in modules:
            mod_auth_for_type = mod.authority.get(entity_type, 0.0)
            if (
                mod_auth_for_type >= _HIGH_AUTHORITY_THRESHOLD
                and mod.name not in sources
                and mod.name in successful_modules
            ):
                weighted *= _CONTRADICTION_FACTOR

        action: MergeAction
        reason: str

        # 4. Confidence gate.
        gate = gates.get(entity_type, _DEFAULT_GATE)
        if weighted < gate:
            action = MergeAction.DROPPED
            reason = f"below_gate ({weighted:.3f} < {gate})"
        # 5. Blocklist check.
        elif blocklist is not None and blocklist.is_blocklisted(entity_type, canonical_value):
            action = MergeAction.DROPPED
            reason = "blocklisted"
        else:
            action = MergeAction.BOOSTED if len(sources) > 1 else MergeAction.KEPT
            reason = (
                f"multi_source_boost ({'+'.join(sources)})" if len(sources) > 1 else f"single_source ({sources[0]})"
            )
            merged.append(
                ScoredEntity(
                    entity_type=entity_type,
                    value=best_entity.value,
                    canonical_value=canonical_value,
                    confidence=round(weighted, 4),
                    source_module=best_entity.source_module,
                    span=best_entity.span,
                )
            )

        if include_merge_log:
            merge_log.append(
                MergeDecision(
                    entity_type=entity_type,
                    value=canonical_value,
                    action=action,
                    reason=reason,
                    final_confidence=round(weighted, 4),
                    sources=sources,
                )
            )

    return merged, merge_log
