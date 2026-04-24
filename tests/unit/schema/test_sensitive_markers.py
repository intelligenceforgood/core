"""Tests that sensitive column markers are exactly as specified per sprint.

Enforcement rule: every column with ``info={"sensitive": True}`` in the
SQLAlchemy METADATA must be in the expected set, and the expected set must
be a subset of the actual set.  An exact equality check ensures we neither
add unmarked sensitive columns nor drop the marking accidentally.

Sprint 1 sensitive column set: {"threat_actors.real_name"}
"""

from __future__ import annotations

from i4g.store.sql import METADATA


def _collect_sensitive_columns() -> set[str]:
    """Return ``{table_name.column_name}`` for every column marked sensitive."""
    result: set[str] = set()
    for table in METADATA.tables.values():
        for col in table.columns:
            if col.info.get("sensitive"):
                result.add(f"{table.name}.{col.name}")
    return result


class TestSensitiveMarkersSprintOne:
    def test_sprint1_sensitive_columns_exact(self):
        expected = {"threat_actors.real_name"}
        actual = _collect_sensitive_columns()
        assert expected <= actual, f"Missing sensitive markers: {expected - actual}"
        assert actual == expected, f"Unexpected sensitive columns (not in Sprint 1 spec): {actual - expected}"
