"""Tests for i4g.store.dossier_queue_store — SQLAlchemy-backed dossier plan queue."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from i4g.store.dossier_queue_store import DossierQueueStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_store(tmp_path) -> DossierQueueStore:
    """Create a DossierQueueStore backed by a fresh in-memory SQLite DB."""
    db_path = tmp_path / "test_dossier.db"
    return DossierQueueStore(db_path=str(db_path))


def _make_plan(plan_id: str = "plan-001") -> MagicMock:
    """Return a mock DossierPlan with the minimal interface needed."""
    plan = MagicMock()
    plan.plan_id = plan_id
    plan.to_dict.return_value = {
        "plan_id": plan_id,
        "jurisdiction_key": "US-CA",
        "created_at": datetime.now(UTC).isoformat(),
        "total_loss_usd": "10000.00",
        "bundle_reason": "test bundle",
        "cross_border": False,
        "shared_drive_parent_id": None,
        "cases": [],
    }
    return plan


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEnqueuePlan:
    def test_enqueue_returns_plan_id(self, tmp_path):
        store = _make_store(tmp_path)
        plan = _make_plan("plan-abc")
        result = store.enqueue_plan(plan)
        assert result == "plan-abc"

    def test_enqueue_creates_pending_entry(self, tmp_path):
        store = _make_store(tmp_path)
        plan = _make_plan("plan-001")
        store.enqueue_plan(plan)

        row = store.get_plan("plan-001")
        assert row is not None
        assert row["status"] == "pending"
        assert row["priority"] == "normal"

    def test_enqueue_with_priority(self, tmp_path):
        store = _make_store(tmp_path)
        plan = _make_plan("plan-002")
        store.enqueue_plan(plan, priority="high")

        row = store.get_plan("plan-002")
        assert row["priority"] == "high"

    def test_upsert_resets_to_pending(self, tmp_path):
        store = _make_store(tmp_path)
        plan = _make_plan("plan-003")
        store.enqueue_plan(plan)
        store.mark_failed("plan-003", error="boom")

        # Re-enqueue should reset to pending
        store.enqueue_plan(plan)
        row = store.get_plan("plan-003")
        assert row["status"] == "pending"
        assert row["error"] is None


class TestListPending:
    def test_returns_only_pending(self, tmp_path):
        store = _make_store(tmp_path)
        store.enqueue_plan(_make_plan("p1"))
        store.enqueue_plan(_make_plan("p2"))
        store.mark_complete("p1")

        pending = store.list_pending()
        assert len(pending) == 1
        assert pending[0]["plan_id"] == "p2"

    def test_respects_limit(self, tmp_path):
        store = _make_store(tmp_path)
        for i in range(5):
            store.enqueue_plan(_make_plan(f"p{i}"))

        pending = store.list_pending(limit=2)
        assert len(pending) == 2


class TestListPlans:
    def test_list_all(self, tmp_path):
        store = _make_store(tmp_path)
        store.enqueue_plan(_make_plan("p1"))
        store.enqueue_plan(_make_plan("p2"))

        plans = store.list_plans()
        assert len(plans) == 2

    def test_filter_by_status(self, tmp_path):
        store = _make_store(tmp_path)
        store.enqueue_plan(_make_plan("p1"))
        store.enqueue_plan(_make_plan("p2"))
        store.mark_failed("p2", error="test error")

        failed = store.list_plans(status="failed")
        assert len(failed) == 1
        assert failed[0]["plan_id"] == "p2"


class TestGetPlan:
    def test_returns_none_for_missing(self, tmp_path):
        store = _make_store(tmp_path)
        assert store.get_plan("nonexistent") is None

    def test_returns_deserialized_payload(self, tmp_path):
        store = _make_store(tmp_path)
        store.enqueue_plan(_make_plan("p1"))

        row = store.get_plan("p1")
        assert row is not None
        assert row["payload"]["plan_id"] == "p1"
        assert row["payload"]["jurisdiction_key"] == "US-CA"


class TestMarkComplete:
    def test_sets_completed_status(self, tmp_path):
        store = _make_store(tmp_path)
        store.enqueue_plan(_make_plan("p1"))
        store.mark_complete("p1")

        row = store.get_plan("p1")
        assert row["status"] == "completed"

    def test_with_warnings(self, tmp_path):
        store = _make_store(tmp_path)
        store.enqueue_plan(_make_plan("p1"))
        store.mark_complete("p1", warnings=["missing_data", "low_confidence"])

        row = store.get_plan("p1")
        assert row["status"] == "completed"
        assert "missing_data" in row["warnings"]
        assert "low_confidence" in row["warnings"]


class TestMarkFailed:
    def test_sets_failed_status_with_error(self, tmp_path):
        store = _make_store(tmp_path)
        store.enqueue_plan(_make_plan("p1"))
        store.mark_failed("p1", error="Agent crashed")

        row = store.get_plan("p1")
        assert row["status"] == "failed"
        assert row["error"] == "Agent crashed"


class TestReset:
    def test_resets_to_pending(self, tmp_path):
        store = _make_store(tmp_path)
        store.enqueue_plan(_make_plan("p1"))
        store.mark_failed("p1", error="transient")
        store.reset("p1")

        row = store.get_plan("p1")
        assert row["status"] == "pending"


class TestLeaseNext:
    def test_leases_oldest_pending(self, tmp_path):
        store = _make_store(tmp_path)
        store.enqueue_plan(_make_plan("p1"))
        store.enqueue_plan(_make_plan("p2"))

        leased = store.lease_next()
        assert leased is not None
        assert leased["plan_id"] == "p1"

        # Verify it's now leased (not re-leasable)
        row = store.get_plan("p1")
        assert row["status"] == "leased"

    def test_returns_none_when_empty(self, tmp_path):
        store = _make_store(tmp_path)
        assert store.lease_next() is None

    def test_skips_already_leased(self, tmp_path):
        store = _make_store(tmp_path)
        store.enqueue_plan(_make_plan("p1"))
        store.enqueue_plan(_make_plan("p2"))
        store.lease_next()  # leases p1

        leased = store.lease_next()
        assert leased is not None
        assert leased["plan_id"] == "p2"


class TestFullLifecycle:
    def test_enqueue_lease_complete(self, tmp_path):
        """Full happy-path lifecycle: enqueue → lease → complete."""
        store = _make_store(tmp_path)
        plan = _make_plan("lifecycle-01")
        store.enqueue_plan(plan, priority="high")

        # Verify pending
        pending = store.list_pending()
        assert len(pending) == 1

        # Lease
        leased = store.lease_next()
        assert leased["plan_id"] == "lifecycle-01"
        assert leased["priority"] == "high"

        # Mark complete
        store.mark_complete("lifecycle-01", warnings=["partial success"])

        # Verify final state
        row = store.get_plan("lifecycle-01")
        assert row["status"] == "completed"
        assert row["warnings"] == ["partial success"]

        # No more pending
        assert store.list_pending() == []
