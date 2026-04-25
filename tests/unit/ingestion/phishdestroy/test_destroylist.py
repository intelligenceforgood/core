"""Tests for the PhishDestroy destroylist ingestion module."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from i4g.ingestion.phishdestroy.destroylist import ingest_destroylist
from i4g.store.blocklist_hit_store import BlocklistHitStore

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "destroylist_sample.json"

_PINNED_SHA = "c40cbbf527dd9e5e232090346e1a8ceab32d1683"
_INGEST_JOB = "test-ingest-destroylist"


def _make_store(tmp_path: Path) -> BlocklistHitStore:
    """Build a file-backed SQLite BlocklistHitStore for tests."""
    db_path = tmp_path / "test_destroylist.db"
    return BlocklistHitStore(db_path=str(db_path))


class TestIngestDestroylistGoldenFixture:
    """Golden-path tests using the trimmed sample fixture."""

    def test_unique_domain_count(self, tmp_path: Path) -> None:
        """3 emails × varying domains → 7 unique normalized domains."""
        store = _make_store(tmp_path)
        summary = ingest_destroylist(
            data_path=FIXTURE_PATH,
            commit_sha=_PINNED_SHA,
            ingest_job=_INGEST_JOB,
            store=store,
        )
        # fakecrypto, scamwallet, notabank, foo, ponzizone, cryptofake, maliciousdapp
        assert summary.unique_domains == 7
        assert summary.rows_inserted == 7
        assert summary.rows_updated == 0
        assert summary.rows_unchanged == 0

    def test_source_provenance_shape(self, tmp_path: Path) -> None:
        """Every row must carry a source_provenance matching §1 of the contract."""
        store = _make_store(tmp_path)
        now = datetime(2026, 4, 24, 12, 0, 0, tzinfo=UTC)
        ingest_destroylist(
            data_path=FIXTURE_PATH,
            commit_sha=_PINNED_SHA,
            ingest_job=_INGEST_JOB,
            store=store,
            now=now,
        )
        rows = store.list_by_source("phishdestroy.destroylist", limit=100)
        assert len(rows) == 7

        required_keys = {"source", "commit_sha", "record_id", "ingested_at", "ingest_job"}
        for row in rows:
            prov = row["source_provenance"]
            assert isinstance(prov, dict), f"source_provenance is not a dict for {row['indicator_id']}"
            assert required_keys.issubset(
                prov.keys()
            ), f"Missing keys {required_keys - prov.keys()} in provenance for {row['indicator_id']}"
            assert prov["source"] == "phishdestroy.destroylist"
            assert prov["commit_sha"] == _PINNED_SHA
            # record_id must be sha256(domain).hexdigest()
            expected_record_id = hashlib.sha256(row["indicator_id"].encode()).hexdigest()
            assert prov["record_id"] == expected_record_id
            # ingested_at must parse as RFC 3339 UTC
            dt = datetime.fromisoformat(prov["ingested_at"].rstrip("Z"))
            assert dt.year >= 2026
            assert prov["ingested_at"].endswith("Z"), "ingested_at must end with Z"
            assert prov["ingest_job"] == _INGEST_JOB


class TestIdempotency:
    """Re-running against unchanged input must produce 0 inserted, N unchanged."""

    def test_second_run_is_noop(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        summary1 = ingest_destroylist(
            data_path=FIXTURE_PATH,
            commit_sha=_PINNED_SHA,
            ingest_job=_INGEST_JOB,
            store=store,
        )
        assert summary1.rows_inserted > 0

        summary2 = ingest_destroylist(
            data_path=FIXTURE_PATH,
            commit_sha=_PINNED_SHA,
            ingest_job=_INGEST_JOB,
            store=store,
        )
        assert summary2.rows_inserted == 0
        assert summary2.rows_updated == 0
        assert summary2.rows_unchanged == summary1.unique_domains


class TestDomainNormalization:
    """'  Foo.COM ' and 'foo.com' must collapse to a single row indicator_id='foo.com'."""

    def test_whitespace_and_case_dedup(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        summary = ingest_destroylist(
            data_path=FIXTURE_PATH,
            commit_sha=_PINNED_SHA,
            ingest_job=_INGEST_JOB,
            store=store,
        )
        rows = store.list_by_source("phishdestroy.destroylist", limit=100)
        indicator_ids = {r["indicator_id"] for r in rows}

        assert "foo.com" in indicator_ids
        assert "  Foo.COM " not in indicator_ids
        assert "Foo.COM" not in indicator_ids
        # Exactly one row for the deduped domain
        foo_rows = [r for r in rows if r["indicator_id"] == "foo.com"]
        assert len(foo_rows) == 1
        # Insertion count should reflect dedup
        assert summary.unique_domains == 7  # not 12 raw entries, not 8


class TestEdgeCases:
    """Empty domains list and whitespace strings are skipped without error."""

    def test_empty_and_whitespace_skipped(self, tmp_path: Path) -> None:
        """Whitespace-only domain '   ' in fixture must be silently skipped."""
        store = _make_store(tmp_path)
        summary = ingest_destroylist(
            data_path=FIXTURE_PATH,
            commit_sha=_PINNED_SHA,
            ingest_job=_INGEST_JOB,
            store=store,
        )
        rows = store.list_by_source("phishdestroy.destroylist", limit=100)
        for row in rows:
            assert row["indicator_id"].strip() != "", "Empty/whitespace domain should not be stored"
        # The blank "   " entry did not become a row
        assert summary.unique_domains == 7

    def test_empty_emails_list(self, tmp_path: Path, tmp_path_factory) -> None:
        """An email entry with an empty domains list does not error."""
        data = {"emails": [{"email": "a@b.com", "domains": []}]}
        fixture_path = tmp_path / "empty.json"
        fixture_path.write_text(json.dumps(data))

        store = _make_store(tmp_path)
        summary = ingest_destroylist(
            data_path=fixture_path,
            commit_sha=_PINNED_SHA,
            ingest_job=_INGEST_JOB,
            store=store,
        )
        assert summary.unique_domains == 0
        assert summary.rows_inserted == 0
