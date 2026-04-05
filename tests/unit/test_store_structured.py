"""
Unit tests for i4g.store.schema and i4g.store.structured.

These tests validate that:
- ScamRecord serialization works correctly.
- StructuredStore performs basic CRUD and search operations.
- SQLite persistence layer behaves deterministically in isolation.

No external dependencies or actual data directories are used;
tests run on an in-memory SQLite database for full isolation.
"""

import pytest
import sqlalchemy as sa

from i4g.store import sql as sql_schema
from i4g.store.schema import ScamRecord
from i4g.store.structured import StructuredStore


@pytest.fixture
def record_sample() -> ScamRecord:
    """Return a sample ScamRecord instance."""
    return ScamRecord(
        case_id="case-001",
        text="Hi I'm Anna from TrustWallet. Send 50 USDT to 0xAbC...",
        entities={
            "people": ["Anna"],
            "wallet_addresses": ["0xAbC..."],
            "scam_indicators": ["verification fee"],
        },
        classification="crypto_investment",
        confidence=0.87,
    )


@pytest.fixture
def temp_store(tmp_path):
    """Provide a temporary in-memory StructuredStore instance."""
    db_path = tmp_path / "test_store.db"
    store = StructuredStore(str(db_path))
    yield store
    store.close()


# ---------------------------------------------------------------------------
# Schema Tests
# ---------------------------------------------------------------------------


def test_scamrecord_serialization_roundtrip(record_sample):
    """Ensure ScamRecord serializes to/from dict properly."""
    d = record_sample.to_dict()
    assert isinstance(d, dict)
    assert "case_id" in d and d["case_id"] == "case-001"
    assert "created_at" in d and isinstance(d["created_at"], str)

    restored = ScamRecord.from_dict(d)
    assert isinstance(restored, ScamRecord)
    assert restored.case_id == record_sample.case_id
    assert abs((restored.created_at - record_sample.created_at).total_seconds()) < 2


# ---------------------------------------------------------------------------
# Structured Store CRUD Tests
# ---------------------------------------------------------------------------


def test_upsert_and_get_by_id(temp_store, record_sample):
    """Insert a record and retrieve it by ID."""
    temp_store.upsert_record(record_sample)
    result = temp_store.get_by_id("case-001")
    assert result is not None
    assert result.case_id == "case-001"
    assert result.classification == "crypto_investment"
    assert "Anna" in result.entities["people"]


def test_upsert_overwrite(temp_store, record_sample):
    """Ensure upsert updates existing rows."""
    temp_store.upsert_record(record_sample)
    record_sample.classification = "romance_scam"
    temp_store.upsert_record(record_sample)
    result = temp_store.get_by_id("case-001")
    assert result.classification == "romance_scam"


def test_list_recent_returns_sorted(temp_store, record_sample):
    """Insert multiple records and ensure sorting by created_at descending."""
    rec1 = record_sample
    rec2 = ScamRecord(
        case_id="case-002",
        text="Dear John, send BTC to 1FzWL...",
        entities={"people": ["John"], "wallet_addresses": ["1FzWL..."]},
        classification="romance_scam",
        confidence=0.91,
    )
    temp_store.upsert_record(rec1)
    temp_store.upsert_record(rec2)
    recent = temp_store.list_recent()
    assert [r.case_id for r in recent] == ["case-002", "case-001"]


def test_search_by_field_simple(temp_store, record_sample):
    """Search by simple top-level fields (case_id, classification)."""
    temp_store.upsert_record(record_sample)
    results = temp_store.search_by_field("classification", "crypto_investment")
    assert len(results) == 1
    assert results[0].case_id == "case-001"


def test_search_by_field_entities_match(temp_store, record_sample, tmp_path):
    """Search inside entities table when supported."""
    temp_store.upsert_record(record_sample)
    # Insert entity row since entity search now joins the entities table
    db_path = tmp_path / "test_store.db"
    engine = sa.create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    with engine.begin() as conn:
        conn.execute(
            sa.insert(sql_schema.entities).values(
                entity_id="ent-1",
                case_id="case-001",
                entity_type="wallet_addresses",
                canonical_value="0xAbC...",
                raw_value="0xAbC...",
                confidence=0.87,
                first_seen_at=record_sample.created_at,
                last_seen_at=record_sample.created_at,
                created_at=record_sample.created_at,
                updated_at=record_sample.created_at,
            )
        )
    results = temp_store.search_by_field("wallet_addresses", "0xAbC")
    assert len(results) == 1
    assert results[0].case_id == "case-001"


def test_search_by_confidence_threshold(temp_store, record_sample):
    """Support numeric comparisons in confidence field."""
    temp_store.upsert_record(record_sample)
    above = temp_store.search_by_field("confidence", ">0.8")
    below = temp_store.search_by_field("confidence", "<0.5")
    assert len(above) == 1
    assert len(below) == 0


def test_delete_by_id(temp_store, record_sample):
    """Verify record deletion."""
    temp_store.upsert_record(record_sample)
    deleted = temp_store.delete_by_id("case-001")
    assert deleted is True
    assert temp_store.get_by_id("case-001") is None


def test_get_by_id_nonexistent(temp_store):
    """Fetching a missing record returns None."""
    assert temp_store.get_by_id("no-such-case") is None
