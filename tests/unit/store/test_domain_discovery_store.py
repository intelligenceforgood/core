"""Tests for DomainDiscoveryStore."""

from __future__ import annotations

from datetime import UTC, datetime

from i4g.store.domain_discovery_store import DomainDiscoveryStore


def _make_store(tmp_path) -> DomainDiscoveryStore:
    db_path = tmp_path / "test_domain_discovery.db"
    return DomainDiscoveryStore(db_path=str(db_path))


class TestDomainDiscoveryInsert:
    def test_insert_returns_discovery_id(self, tmp_path):
        store = _make_store(tmp_path)
        seen_at = datetime(2026, 4, 1, tzinfo=UTC)
        record = store.insert(domain="example.com", source="merklemap", seen_at=seen_at)
        assert record["discovery_id"] is not None
        assert record["domain"] == "example.com"

    def test_insert_persists_row(self, tmp_path):
        store = _make_store(tmp_path)
        seen_at = datetime(2026, 4, 2, tzinfo=UTC)
        record = store.insert(
            domain="phish.example.com",
            source="crtsh",
            seen_at=seen_at,
            filter_match=True,
            filter_reason="keyword_match",
        )
        results = store.list_recent_matches()
        assert len(results) == 1
        assert results[0]["discovery_id"] == record["discovery_id"]
        assert results[0]["filter_reason"] == "keyword_match"

    def test_insert_multiple_rows_allowed(self, tmp_path):
        """domain_discoveries has no unique constraint; multiple rows for same domain are allowed."""
        store = _make_store(tmp_path)
        t = datetime(2026, 4, 3, tzinfo=UTC)
        store.insert(domain="dup.com", source="merklemap", seen_at=t)
        store.insert(domain="dup.com", source="merklemap", seen_at=t)
        results = store.list_recent_matches(limit=10)
        # Neither row has filter_match=True, so list_recent_matches returns 0
        assert results == []


class TestDomainDiscoveryListRecentMatches:
    def test_returns_only_filter_matches(self, tmp_path):
        store = _make_store(tmp_path)
        t = datetime(2026, 4, 4, tzinfo=UTC)
        store.insert(domain="safe.com", source="merklemap", seen_at=t, filter_match=False)
        store.insert(domain="phish.com", source="crtsh", seen_at=t, filter_match=True)

        matches = store.list_recent_matches()
        assert len(matches) == 1
        assert matches[0]["domain"] == "phish.com"

    def test_respects_limit(self, tmp_path):
        store = _make_store(tmp_path)
        t = datetime(2026, 4, 5, tzinfo=UTC)
        for i in range(5):
            store.insert(domain=f"phish{i}.com", source="merklemap", seen_at=t, filter_match=True)

        results = store.list_recent_matches(limit=3)
        assert len(results) == 3


class TestDomainDiscoveryMarkEnqueued:
    def test_mark_enqueued_sets_scan_id(self, tmp_path):
        store = _make_store(tmp_path)
        t = datetime(2026, 4, 6, tzinfo=UTC)
        record = store.insert(domain="todo.com", source="merklemap", seen_at=t)
        updated = store.mark_enqueued(record["discovery_id"], "scan-xyz")
        assert updated is not None
        assert updated["enqueued_scan_id"] == "scan-xyz"

    def test_mark_enqueued_returns_none_for_missing(self, tmp_path):
        store = _make_store(tmp_path)
        assert store.mark_enqueued("no-such-id", "scan-abc") is None


class TestDomainDiscoveryDismiss:
    def test_dismiss_marks_row_and_excludes_from_list(self, tmp_path):
        store = _make_store(tmp_path)
        t = datetime(2026, 4, 10, tzinfo=UTC)
        record = store.insert(domain="dismiss-me.com", source="merklemap", seen_at=t, filter_match=True)
        discovery_id = record["discovery_id"]

        before_count = store.count_recent_matches()
        assert before_count == 1

        updated = store.dismiss(discovery_id, reason="not relevant")
        assert updated is not None
        assert updated["dismissed_at"] is not None
        assert updated["dismiss_reason"] == "not relevant"

        # Should no longer appear in list_recent_matches
        matches = store.list_recent_matches()
        assert all(r["discovery_id"] != discovery_id for r in matches)

        # count should decrease
        after_count = store.count_recent_matches()
        assert after_count == before_count - 1

    def test_dismiss_unknown_returns_none(self, tmp_path):
        store = _make_store(tmp_path)
        assert store.dismiss("nonexistent-id", reason="x") is None

    def test_list_recent_matches_since_filter(self, tmp_path):
        store = _make_store(tmp_path)
        t_old = datetime(2026, 3, 1, tzinfo=UTC)
        t_new = datetime(2026, 4, 20, tzinfo=UTC)
        store.insert(domain="old.com", source="merklemap", seen_at=t_old, filter_match=True)
        record_new = store.insert(domain="new.com", source="merklemap", seen_at=t_new, filter_match=True)

        # Without since: both rows returned
        all_matches = store.list_recent_matches()
        assert len(all_matches) == 2

        # With since=t_new: only the newer row
        filtered = store.list_recent_matches(since=t_new)
        assert len(filtered) == 1
        assert filtered[0]["discovery_id"] == record_new["discovery_id"]

        # count_recent_matches honours since too
        assert store.count_recent_matches(since=t_new) == 1
