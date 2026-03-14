"""Unit tests for watchlist — CRUD, alert threshold logic, notification generation (S5-28)."""

from __future__ import annotations

from pathlib import Path

import pytest

from i4g.store.watchlist_store import WatchlistStore


@pytest.fixture()
def store(tmp_path: Path) -> WatchlistStore:
    """Create a WatchlistStore backed by a temporary SQLite database."""
    db_path = tmp_path / "test_watchlist.db"
    return WatchlistStore(db_path=db_path)


def test_add_and_get_item(store: WatchlistStore) -> None:
    """Adding an item and retrieving it returns consistent data."""
    wid = store.add_item(
        entity_type="crypto_wallet",
        canonical_value="0xABC123",
        alert_on_new_case=True,
        alert_on_loss_increase=False,
        note="Test note",
        created_by="analyst1",
    )
    assert wid

    item = store.get_item(wid)
    assert item is not None
    assert item["entity_type"] == "crypto_wallet"
    assert item["canonical_value"] == "0xABC123"
    assert item["alert_on_new_case"] is True
    assert item["note"] == "Test note"
    assert item["created_by"] == "analyst1"


def test_list_items(store: WatchlistStore) -> None:
    """list_items returns all stored items."""
    store.add_item(entity_type="domain", canonical_value="evil.com")
    store.add_item(entity_type="ip_address", canonical_value="10.0.0.1")

    items = store.list_items()
    assert len(items) == 2


def test_update_item(store: WatchlistStore) -> None:
    """update_item modifies alert settings."""
    wid = store.add_item(
        entity_type="email",
        canonical_value="bad@evil.com",
        alert_on_new_case=True,
        alert_on_loss_increase=False,
    )

    store.update_item(wid, alert_on_loss_increase=True, loss_threshold=50000.0)

    item = store.get_item(wid)
    assert item["alert_on_loss_increase"] is True
    assert float(item["loss_threshold"]) == 50000.0


def test_remove_item(store: WatchlistStore) -> None:
    """remove_item deletes the item."""
    wid = store.add_item(entity_type="domain", canonical_value="gone.com")
    assert store.get_item(wid) is not None

    result = store.remove_item(wid)
    assert result is True
    assert store.get_item(wid) is None


def test_remove_nonexistent(store: WatchlistStore) -> None:
    """Removing a non-existent item returns False."""
    result = store.remove_item("nonexistent-id")
    assert result is False


def test_duplicate_entity_raises(store: WatchlistStore) -> None:
    """Adding the same entity twice raises IntegrityError or returns None."""
    store.add_item(entity_type="domain", canonical_value="dup.com")
    # Second add should fail due to unique constraint
    result = store.add_item(entity_type="domain", canonical_value="dup.com")
    assert result is None  # Store returns None on duplicate


def test_create_and_list_alerts(store: WatchlistStore) -> None:
    """Creating alerts and listing them works correctly."""
    wid = store.add_item(entity_type="domain", canonical_value="alert-test.com")

    aid = store.create_alert(
        watchlist_id=wid,
        alert_type="new_case",
        message="New case found",
        data={"case_id": "case-001"},
    )
    assert aid

    alerts = store.list_alerts(watchlist_id=wid)
    assert len(alerts) == 1
    assert alerts[0]["alert_type"] == "new_case"
    assert alerts[0]["is_read"] is False


def test_mark_alert_read(store: WatchlistStore) -> None:
    """Marking an alert as read updates the flag."""
    wid = store.add_item(entity_type="domain", canonical_value="read-test.com")
    aid = store.create_alert(
        watchlist_id=wid,
        alert_type="loss_increase",
        message="Loss threshold exceeded",
    )

    assert store.mark_alert_read(aid) is True

    alerts = store.list_alerts(watchlist_id=wid)
    assert alerts[0]["is_read"] is True


def test_mark_all_read(store: WatchlistStore) -> None:
    """mark_all_read marks all unread alerts."""
    wid = store.add_item(entity_type="domain", canonical_value="all-read.com")
    store.create_alert(watchlist_id=wid, alert_type="new_case", message="Alert 1")
    store.create_alert(watchlist_id=wid, alert_type="new_case", message="Alert 2")

    count = store.mark_all_read()
    assert count == 2

    unread = store.count_unread_alerts()
    assert unread == 0


def test_count_items(store: WatchlistStore) -> None:
    """count_items returns the correct count."""
    assert store.count_items() == 0
    store.add_item(entity_type="domain", canonical_value="count1.com")
    store.add_item(entity_type="domain", canonical_value="count2.com")
    assert store.count_items() == 2


def test_find_by_entity(store: WatchlistStore) -> None:
    """find_by_entity locates an item by type+value."""
    store.add_item(entity_type="ip_address", canonical_value="192.168.1.1")

    item = store.find_by_entity("ip_address", "192.168.1.1")
    assert item is not None
    assert item["canonical_value"] == "192.168.1.1"

    missing = store.find_by_entity("ip_address", "10.0.0.99")
    assert missing is None
