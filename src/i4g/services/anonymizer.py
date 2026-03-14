"""Researcher data anonymization layer.

Provides PII-stripping transformations for Researcher-role data access.
All entity values with PII potential (bank accounts, phone numbers,
emails, names) are hashed.  Loss amounts are rounded to the nearest
$1,000 to prevent re-identification.

Usage::

    from i4g.services.anonymizer import anonymize_records
    safe_data = anonymize_records(rows, entity_type="bank_account")
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

# Entity types that contain PII and must be anonymized
_PII_ENTITY_TYPES = frozenset(
    {
        "bank_account",
        "phone_number",
        "email",
        "person_name",
        "national_id",
        "passport_number",
        "address",
        "credit_card",
    }
)

# Fields that should be hashed in any record
_PII_FIELDS = frozenset(
    {
        "canonical_value",
        "raw_value",
        "email",
        "phone",
        "name",
        "address",
        "account_number",
        "person_name",
    }
)

# Salt prefix — rotated by configuration; not a secret, just
# ensures hashes differ from other systems.
_HASH_SALT = "i4g-researcher-anon-v1"


def anonymize_value(value: str, *, entity_type: str | None = None) -> str:
    """Hash a single PII value for researcher consumption.

    Non-PII entity types (e.g. ``domain``, ``ip_address``) are returned
    unchanged.

    Args:
        value: Raw entity value.
        entity_type: If provided, only hash for PII entity types.

    Returns:
        Hashed value or original if entity type is non-PII.
    """
    if entity_type and entity_type not in _PII_ENTITY_TYPES:
        return value
    return _hash(value)


def round_loss(amount: float, *, precision: int = 1000) -> float:
    """Round a loss amount to prevent re-identification.

    Args:
        amount: Raw loss value.
        precision: Rounding granularity (default $1,000).

    Returns:
        Rounded value.
    """
    if amount <= 0:
        return 0.0
    return float(math.ceil(amount / precision) * precision)


def anonymize_record(record: dict[str, Any], *, entity_type: str | None = None) -> dict[str, Any]:
    """Anonymize a single record dict.

    Hashes PII fields and rounds loss amounts.

    Args:
        record: Raw data record.
        entity_type: Entity type for context-aware hashing.

    Returns:
        New dict with anonymized values.
    """
    result = {}
    for key, value in record.items():
        if key in _PII_FIELDS and isinstance(value, str):
            etype = entity_type or record.get("entity_type")
            result[key] = anonymize_value(value, entity_type=etype)
        elif key in ("loss_sum", "loss_amount", "total_loss") and isinstance(value, (int, float)):
            result[key] = round_loss(float(value))
        else:
            result[key] = value
    return result


def anonymize_records(
    records: list[dict[str, Any]],
    *,
    entity_type: str | None = None,
) -> list[dict[str, Any]]:
    """Anonymize a list of records for researcher access.

    Args:
        records: Raw data records.
        entity_type: Entity type override for all records.

    Returns:
        New list of anonymized records.
    """
    return [anonymize_record(r, entity_type=entity_type) for r in records]


def _hash(value: str) -> str:
    """Produce a deterministic anonymized hash of a value.

    Args:
        value: Raw string to hash.

    Returns:
        Hex-encoded SHA-256 hash prefix (16 chars).
    """
    return hashlib.sha256(f"{_HASH_SALT}:{value}".encode()).hexdigest()[:16]
