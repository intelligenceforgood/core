"""Normalization package for i4g.

Provides functions and reference data to clean, deduplicate, and canonicalize
entities extracted during the semantic analysis phase.
"""

from i4g.normalization.normalizer import merge_entities, normalize_entities
from i4g.normalization.tokenize import tokenize_fields, tokenize_text

__all__ = [
    "merge_entities",
    "normalize_entities",
    "tokenize_fields",
    "tokenize_text",
]
