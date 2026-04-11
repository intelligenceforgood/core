"""Extraction orchestrator — the single entry point for entity extraction.

Instantiates modules based on settings, fans out extraction to each module,
collects results with timing, and delegates to the merge engine.

Usage::

    from i4g.extraction.orchestrator import extract_entities

    result = extract_entities(text)
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from i4g.extraction.chunking import chunk_text
from i4g.extraction.merge import merge_entities
from i4g.extraction.modules.blocklist import BlocklistModule
from i4g.extraction.modules.heuristic import HeuristicModule
from i4g.extraction.modules.llm import LLMModule
from i4g.extraction.modules.ml_ner import MLNERModule
from i4g.extraction.modules.regex import RegexModule
from i4g.extraction.normalize import normalize_obfuscated_text
from i4g.extraction.types import (
    ExtractionResult,
    ModuleProtocol,
    ModuleReport,
    ModuleStatus,
    ScoredEntity,
)

if TYPE_CHECKING:
    from i4g.llm.client import LLMClient

logger = logging.getLogger(__name__)

# Registry mapping module name → factory. Each factory returns a module instance.
# Factories are callables that accept keyword arguments from the orchestrator.
_MODULE_CLASSES: dict[str, type] = {
    "regex": RegexModule,
    "heuristic": HeuristicModule,
    "llm": LLMModule,
    "ml_ner": MLNERModule,
}


def _build_module(
    name: str,
    *,
    llm_client: LLMClient | None = None,
    ml_predict_fn: object | None = None,
) -> ModuleProtocol | None:
    """Instantiate a module by name, injecting dependencies as needed.

    Args:
        name: Module name (e.g. ``"regex"``, ``"llm"``).
        llm_client: Required when *name* is ``"llm"``.
        ml_predict_fn: Required when *name* is ``"ml_ner"``.

    Returns:
        A ``ModuleProtocol`` instance, or ``None`` if the module can't be
        built (e.g. missing dependency).
    """
    if name == "llm":
        if llm_client is None:
            logger.warning("LLM client not provided; skipping llm module")
            return None
        return LLMModule(llm_client)
    if name == "ml_ner":
        if ml_predict_fn is None:
            logger.warning("ML predict function not provided; skipping ml_ner module")
            return None
        return MLNERModule(ml_predict_fn)  # type: ignore[arg-type]
    cls = _MODULE_CLASSES.get(name)
    if cls is None:
        logger.warning("Unknown extraction module: %s", name)
        return None
    return cls()  # type: ignore[call-arg]


def _run_module(module: ModuleProtocol, text: str) -> tuple[list[ScoredEntity], ModuleReport]:
    """Execute a single module with timing and error handling.

    Returns:
        ``(entities, report)`` — on failure, entities is empty and report
        has ``status=FAILED``.
    """
    start = time.monotonic()
    try:
        entities = module.extract(text)
        elapsed = time.monotonic() - start
        return entities, ModuleReport(
            module_name=module.name,
            status=ModuleStatus.SUCCESS,
            entity_count=len(entities),
            elapsed_seconds=round(elapsed, 4),
        )
    except Exception as exc:
        elapsed = time.monotonic() - start
        logger.warning("Module %s failed: %s", module.name, exc, exc_info=True)
        return [], ModuleReport(
            module_name=module.name,
            status=ModuleStatus.FAILED,
            entity_count=0,
            elapsed_seconds=round(elapsed, 4),
            error=str(exc),
        )


def extract_entities(
    text: str,
    *,
    modules: list[str] | None = None,
    confidence_gates: dict[str, float] | None = None,
    include_merge_log: bool = False,
    llm_client: LLMClient | None = None,
    ml_predict_fn: object | None = None,
    blocklist_path: Path | None = None,
) -> ExtractionResult:
    """Run the full extraction pipeline on *text*.

    This is the **sole public interface** to the extraction subsystem.

    Args:
        text: Input text to extract entities from.
        modules: Module names to run. If ``None``, reads from settings.
        confidence_gates: Per-type thresholds. If ``None``, reads from settings.
        include_merge_log: Include ``MergeDecision`` audit trail in the result.
        llm_client: LLM client instance (required if ``"llm"`` is enabled).
        ml_predict_fn: ML NER prediction callable (required if ``"ml_ner"``
            is enabled).
        blocklist_path: Path to TOML blocklist config. If ``None``, uses the
            built-in default blocklist.

    Returns:
        ``ExtractionResult`` with merged entities, module reports, and
        optional merge log.
    """
    from i4g.settings import get_settings

    settings = get_settings()

    # Resolve module list from settings if not explicitly provided.
    module_names = modules if modules is not None else list(settings.extraction.enabled_modules)

    # Resolve confidence gates from settings if not explicitly provided.
    gates = confidence_gates if confidence_gates is not None else settings.extraction.confidence_gates()

    # Build module instances.
    active_modules: list[ModuleProtocol] = []
    for name in module_names:
        mod = _build_module(name, llm_client=llm_client, ml_predict_fn=ml_predict_fn)
        if mod is not None:
            active_modules.append(mod)

    if not active_modules:
        logger.warning("No extraction modules available; returning empty result")
        return ExtractionResult()

    # Pre-process: de-obfuscate scammer patterns before module dispatch.
    normalized_text = normalize_obfuscated_text(text)

    # Chunk large documents that exceed LLM context limits.
    chunks = chunk_text(normalized_text)

    # Fan-out: run each module on each chunk, then aggregate.
    all_entities: list[ScoredEntity] = []
    all_reports: list[ModuleReport] = []
    for mod in active_modules:
        mod_entities: list[ScoredEntity] = []
        mod_elapsed = 0.0
        mod_errors: list[str] = []
        mod_statuses: list[ModuleStatus] = []

        for chunk in chunks:
            entities, report = _run_module(mod, chunk.text)
            # Adjust span offsets to the full document position.
            if chunk.offset > 0:
                adjusted: list[ScoredEntity] = []
                for ent in entities:
                    if ent.span is not None:
                        adjusted.append(
                            ScoredEntity(
                                entity_type=ent.entity_type,
                                value=ent.value,
                                canonical_value=ent.canonical_value,
                                confidence=ent.confidence,
                                source_module=ent.source_module,
                                span=(ent.span[0] + chunk.offset, ent.span[1] + chunk.offset),
                            )
                        )
                    else:
                        adjusted.append(ent)
                mod_entities.extend(adjusted)
            else:
                mod_entities.extend(entities)
            mod_elapsed += report.elapsed_seconds
            mod_statuses.append(report.status)
            if report.error:
                mod_errors.append(report.error)

        # Combine per-chunk reports into a single module report.
        if ModuleStatus.FAILED in mod_statuses and ModuleStatus.SUCCESS in mod_statuses:
            combined_status = ModuleStatus.PARTIAL
        elif all(s == ModuleStatus.FAILED for s in mod_statuses):
            combined_status = ModuleStatus.FAILED
        else:
            combined_status = ModuleStatus.SUCCESS

        all_entities.extend(mod_entities)
        all_reports.append(
            ModuleReport(
                module_name=mod.name,
                status=combined_status,
                entity_count=len(mod_entities),
                elapsed_seconds=round(mod_elapsed, 4),
                error="; ".join(mod_errors) if mod_errors else None,
            )
        )

    # Build blocklist for merge filtering.
    blocklist = BlocklistModule(config_path=blocklist_path)

    # Merge: authority-ranked dedup, agreement bonus, contradiction penalty,
    # confidence gating, blocklist filtering.
    merged, merge_log = merge_entities(
        all_entities,
        modules=active_modules,
        module_reports=all_reports,
        confidence_gates=gates,
        blocklist=blocklist,
        include_merge_log=include_merge_log,
    )

    return ExtractionResult(
        entities=merged,
        module_reports=all_reports,
        merge_log=merge_log,
    )
