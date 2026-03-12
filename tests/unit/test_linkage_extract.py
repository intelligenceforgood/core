"""Unit tests for the linkage extraction job.

Tests cover LLM response parsing, indicator matching,
and the end-to-end _process_intake pipeline.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from i4g.store.sql import (
    METADATA,
    cases,
    indicators,
    intake_indicator_links,
    intake_records,
)
from i4g.worker.jobs.linkage_extract import (
    _match_indicators,
    _parse_extraction_response,
    _process_intake,
)


def _make_session(db_path: Path) -> sessionmaker:
    """Create a sessionmaker with all tables."""
    engine = sa.create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    METADATA.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


# ---------------------------------------------------------------------------
# _parse_extraction_response
# ---------------------------------------------------------------------------


def test_parse_valid_json_array() -> None:
    """Valid JSON array is parsed correctly."""
    response = '[{"type": "wallet", "value": "0xABC", "confidence": 0.9}]'
    result = _parse_extraction_response(response)
    assert len(result) == 1
    assert result[0]["type"] == "wallet"
    assert result[0]["value"] == "0xABC"
    assert result[0]["confidence"] == 0.9


def test_parse_json_code_block() -> None:
    """JSON wrapped in markdown code block is extracted."""
    response = '```json\n[{"type": "phone", "value": "+15551234567", "confidence": 0.8}]\n```'
    result = _parse_extraction_response(response)
    assert len(result) == 1
    assert result[0]["type"] == "phone"


def test_parse_empty_array() -> None:
    """Empty array returns empty list."""
    assert _parse_extraction_response("[]") == []


def test_parse_invalid_json() -> None:
    """Invalid JSON raises an error."""
    with pytest.raises((json.JSONDecodeError, ValueError)):
        _parse_extraction_response("not json at all")


def test_parse_skips_items_without_value() -> None:
    """Items missing 'value' are filtered out."""
    response = '[{"type": "wallet", "confidence": 0.9}]'
    result = _parse_extraction_response(response)
    assert len(result) == 0


def test_parse_multiple_indicators() -> None:
    """Multiple indicators are parsed."""
    response = json.dumps(
        [
            {"type": "wallet", "value": "0xABC", "confidence": 0.9},
            {"type": "email", "value": "scam@example.com", "confidence": 0.7},
            {"type": "url", "value": "https://phishing.example.com", "confidence": 0.6},
        ]
    )
    result = _parse_extraction_response(response)
    assert len(result) == 3


# ---------------------------------------------------------------------------
# _match_indicators
# ---------------------------------------------------------------------------


def test_match_indicators_exact_match(tmp_path: Path) -> None:
    """Exact match on indicator number returns indicator_id."""
    sf = _make_session(tmp_path / "match.db")
    now = datetime.now(tz=UTC)

    with sf() as session:
        session.execute(
            cases.insert().values(
                case_id="c1",
                dataset="test",
                source_type="reactive",
                raw_text_sha256="h1",
                status="open",
                created_at=now,
                updated_at=now,
            )
        )
        session.execute(
            indicators.insert().values(
                indicator_id="ind-1",
                case_id="c1",
                category="crypto",
                type="bitcoin",
                number="1BTC123ABC",
                status="active",
                confidence=0.95,
                dataset="test",
                first_seen_at=now,
                last_seen_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()

    with sf() as session:
        extracted = [{"type": "wallet", "value": "1BTC123ABC", "confidence": 0.9}]
        matches = _match_indicators(session, extracted)
        assert len(matches) == 1
        assert matches[0] == ("ind-1", 0.9)


def test_match_indicators_no_match(tmp_path: Path) -> None:
    """No match returns empty list."""
    sf = _make_session(tmp_path / "match.db")
    with sf() as session:
        extracted = [{"type": "wallet", "value": "nonexistent", "confidence": 0.9}]
        matches = _match_indicators(session, extracted)
        assert matches == []


# ---------------------------------------------------------------------------
# _process_intake
# ---------------------------------------------------------------------------


class _MockLLMClient:
    """Minimal LLM client stub for testing."""

    def __init__(self, response: str) -> None:
        self._response = response

    def generate(self, prompt: str) -> str:
        return self._response


def test_process_intake_creates_links(tmp_path: Path) -> None:
    """_process_intake writes intake_indicator_links for matched indicators."""
    sf = _make_session(tmp_path / "process.db")
    now = datetime.now(tz=UTC)

    with sf() as session:
        session.execute(
            cases.insert().values(
                case_id="c1",
                dataset="test",
                source_type="reactive",
                raw_text_sha256="h1",
                status="open",
                created_at=now,
                updated_at=now,
            )
        )
        session.execute(
            indicators.insert().values(
                indicator_id="ind-1",
                case_id="c1",
                category="crypto",
                type="bitcoin",
                number="1BTC999",
                status="active",
                confidence=0.95,
                dataset="test",
                first_seen_at=now,
                last_seen_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        session.execute(
            intake_records.insert().values(
                intake_id="ir-1",
                case_id="c1",
                loss_amount=5000.0,
                summary="Sent BTC to 1BTC999",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()

    llm_response = json.dumps(
        [
            {"type": "wallet", "value": "1BTC999", "confidence": 0.85},
        ]
    )
    client = _MockLLMClient(llm_response)

    with sf() as session:
        count = _process_intake(session, client, "ir-1", "Sent BTC to 1BTC999")
        session.commit()

    assert count == 1

    with sf() as session:
        links = session.execute(sa.select(intake_indicator_links)).fetchall()
        assert len(links) == 1
        assert links[0].intake_id == "ir-1"
        assert links[0].indicator_id == "ind-1"
        assert links[0].linked_by == "llm_extraction"


def test_process_intake_no_indicators(tmp_path: Path) -> None:
    """When LLM finds no indicators, zero links are created."""
    sf = _make_session(tmp_path / "process.db")
    client = _MockLLMClient("[]")

    with sf() as session:
        count = _process_intake(session, client, "ir-1", "No indicators here")
    assert count == 0
