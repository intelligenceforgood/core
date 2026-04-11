"""Extraction package for i4g.

This package contains modules for extracting structured and semantic information
from raw text, such as named entities, scam indicators, and other relevant data
points. It includes both rule-based and model-based (LLM) extraction methods.

Public API
----------
The **sole public interface** is :func:`extract_entities`.  All callers should
import from here — never reach into sub-modules directly.

    from i4g.extraction import extract_entities, ExtractionResult

"""

from i4g.extraction.orchestrator import extract_entities
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

__all__ = [
    "extract_entities",
    "ConfidenceGate",
    "ExtractionResult",
    "MergeAction",
    "MergeDecision",
    "ModuleProtocol",
    "ModuleReport",
    "ModuleStatus",
    "ScoredEntity",
]
