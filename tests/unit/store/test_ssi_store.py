"""Tests for i4g.store.ssi_store — SSI scan persistence in core's database.

Covers all four tables (site_scans, harvested_wallets, agent_sessions,
pii_exposures) and exercises every public method on SsiStore against
an in-memory SQLite database.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from i4g.store.ssi_store import SsiStore
from i4g.store.sql import METADATA


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_store(tmp_path) -> SsiStore:
    """Create an SsiStore backed by a fresh SQLite DB in tmp_path."""
    db_path = tmp_path / "test_ssi.db"
    return SsiStore(db_path=str(db_path))


def _make_store_with_factory(tmp_path) -> SsiStore:
    """Create an SsiStore using an explicit session_factory."""
    db_path = tmp_path / "test_ssi_factory.db"
    engine = sa.create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    METADATA.create_all(engine, checkfirst=True)
    sf = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return SsiStore(session_factory=sf)


# ---------------------------------------------------------------------------
# site_scans tests
# ---------------------------------------------------------------------------


class TestCreateScan:
    """Tests for SsiStore.create_scan."""

    def test_create_returns_scan_id(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)
        scan_id = store.create_scan(url="https://example.com")
        assert scan_id
        assert isinstance(scan_id, str)
        assert len(scan_id) == 36  # UUID format

    def test_create_sets_running_status(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)
        scan_id = store.create_scan(url="https://example.com", scan_type="full")
        scan = store.get_scan(scan_id)
        assert scan is not None
        assert scan["status"] == "running"
        assert scan["scan_type"] == "full"
        assert scan["url"] == "https://example.com"

    def test_create_with_domain_and_case_id(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)
        scan_id = store.create_scan(
            url="https://scam.example.com/phish",
            domain="scam.example.com",
            case_id="case-001",
            metadata={"initiated_by": "test"},
        )
        scan = store.get_scan(scan_id)
        assert scan["domain"] == "scam.example.com"
        assert scan["case_id"] == "case-001"

    def test_create_via_session_factory(self, tmp_path: object) -> None:
        store = _make_store_with_factory(tmp_path)
        scan_id = store.create_scan(url="https://test.com")
        assert store.get_scan(scan_id) is not None


class TestUpdateScan:
    """Tests for SsiStore.update_scan."""

    def test_update_arbitrary_fields(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)
        scan_id = store.create_scan(url="https://example.com")
        store.update_scan(scan_id, status="paused", domain="example.com")
        scan = store.get_scan(scan_id)
        assert scan["status"] == "paused"
        assert scan["domain"] == "example.com"

    def test_update_sets_updated_at(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)
        scan_id = store.create_scan(url="https://example.com")
        original = store.get_scan(scan_id)
        store.update_scan(scan_id, status="completed")
        updated = store.get_scan(scan_id)
        # updated_at should be at least as recent
        assert updated["updated_at"] >= original["updated_at"]


class TestCompleteScan:
    """Tests for SsiStore.complete_scan."""

    def test_complete_sets_final_status(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)
        scan_id = store.create_scan(url="https://example.com")
        store.complete_scan(scan_id, status="completed", risk_score=85.5, wallet_count=3)
        scan = store.get_scan(scan_id)
        assert scan["status"] == "completed"
        assert float(scan["risk_score"]) == 85.5
        assert scan["wallet_count"] == 3
        assert scan["completed_at"] is not None

    def test_complete_with_all_fields(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)
        scan_id = store.create_scan(url="https://example.com")
        store.complete_scan(
            scan_id,
            status="completed",
            passive_result={"whois": {"registrar": "test"}},
            active_result={"pages_visited": 5},
            classification_result={"label": "phishing", "confidence": 0.95},
            risk_score=92.0,
            taxonomy_version="v2",
            wallet_count=2,
            total_cost_usd=0.05,
            llm_input_tokens=1000,
            llm_output_tokens=500,
            duration_seconds=45.5,
            evidence_path="gs://bucket/evidence.zip",
            evidence_zip_sha256="abc123",
        )
        scan = store.get_scan(scan_id)
        assert scan["passive_result"]["whois"]["registrar"] == "test"
        assert scan["active_result"]["pages_visited"] == 5
        assert scan["classification_result"]["label"] == "phishing"
        assert scan["taxonomy_version"] == "v2"
        assert scan["evidence_path"] == "gs://bucket/evidence.zip"
        assert scan["evidence_zip_sha256"] == "abc123"
        assert scan["llm_input_tokens"] == 1000
        assert scan["llm_output_tokens"] == 500

    def test_complete_failed_with_error(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)
        scan_id = store.create_scan(url="https://example.com")
        store.complete_scan(scan_id, status="failed", error_message="Browser timeout")
        scan = store.get_scan(scan_id)
        assert scan["status"] == "failed"
        assert scan["error_message"] == "Browser timeout"


class TestGetScan:
    """Tests for SsiStore.get_scan."""

    def test_get_nonexistent_returns_none(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)
        assert store.get_scan("nonexistent-id") is None

    def test_get_returns_dict(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)
        scan_id = store.create_scan(url="https://example.com")
        scan = store.get_scan(scan_id)
        assert isinstance(scan, dict)
        assert "scan_id" in scan
        assert "url" in scan
        assert "created_at" in scan


class TestListScans:
    """Tests for SsiStore.list_scans."""

    def test_list_empty(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)
        assert store.list_scans() == []

    def test_list_returns_all(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)
        store.create_scan(url="https://site1.com")
        store.create_scan(url="https://site2.com")
        store.create_scan(url="https://site3.com")
        scans = store.list_scans()
        assert len(scans) == 3

    def test_list_filter_by_domain(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)
        store.create_scan(url="https://evil.com", domain="evil.com")
        store.create_scan(url="https://good.com", domain="good.com")
        scans = store.list_scans(domain="evil.com")
        assert len(scans) == 1
        assert scans[0]["domain"] == "evil.com"

    def test_list_filter_by_status(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)
        sid1 = store.create_scan(url="https://a.com")
        sid2 = store.create_scan(url="https://b.com")
        store.complete_scan(sid1, status="completed")
        scans = store.list_scans(status="running")
        assert len(scans) == 1
        assert scans[0]["scan_id"] == sid2

    def test_list_pagination(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)
        for i in range(5):
            store.create_scan(url=f"https://site{i}.com")
        page1 = store.list_scans(limit=2, offset=0)
        page2 = store.list_scans(limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2
        assert page1[0]["scan_id"] != page2[0]["scan_id"]

    def test_list_ordered_by_created_at_desc(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)
        store.create_scan(url="https://first.com")
        store.create_scan(url="https://second.com")
        scans = store.list_scans()
        # Most recent first
        assert scans[0]["url"] == "https://second.com"
        assert scans[1]["url"] == "https://first.com"


# ---------------------------------------------------------------------------
# harvested_wallets tests
# ---------------------------------------------------------------------------


class TestAddWallet:
    """Tests for SsiStore.add_wallet."""

    def test_add_returns_wallet_id(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)
        scan_id = store.create_scan(url="https://example.com")
        wallet_id = store.add_wallet(
            scan_id=scan_id,
            token_symbol="ETH",
            network_short="ERC20",
            wallet_address="0xabc123",
        )
        assert wallet_id
        assert isinstance(wallet_id, str)

    def test_add_wallet_retrievable(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)
        scan_id = store.create_scan(url="https://example.com")
        store.add_wallet(
            scan_id=scan_id,
            token_symbol="BTC",
            network_short="BTC",
            wallet_address="1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
            source="llm",
            confidence=0.95,
            site_url="https://example.com",
        )
        wallets = store.get_wallets(scan_id)
        assert len(wallets) == 1
        assert wallets[0]["token_symbol"] == "BTC"
        assert wallets[0]["wallet_address"] == "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
        assert wallets[0]["source"] == "llm"

    def test_add_duplicate_wallet_upserts(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)
        scan_id = store.create_scan(url="https://example.com")
        store.add_wallet(
            scan_id=scan_id,
            token_symbol="ETH",
            network_short="ERC20",
            wallet_address="0xabc",
            confidence=0.5,
        )
        store.add_wallet(
            scan_id=scan_id,
            token_symbol="ETH",
            network_short="ERC20",
            wallet_address="0xabc",
            confidence=0.9,
        )
        wallets = store.get_wallets(scan_id)
        # Should have one row with updated confidence
        assert len(wallets) == 1
        assert float(wallets[0]["confidence"]) == 0.9


class TestAddWalletsBulk:
    """Tests for SsiStore.add_wallets_bulk."""

    def test_bulk_empty_returns_zero(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)
        scan_id = store.create_scan(url="https://example.com")
        assert store.add_wallets_bulk(scan_id, []) == 0

    def test_bulk_insert_multiple(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)
        scan_id = store.create_scan(url="https://example.com")
        wallets = [
            {"token_symbol": "ETH", "network_short": "ERC20", "wallet_address": "0x111"},
            {"token_symbol": "BTC", "network_short": "BTC", "wallet_address": "1abc"},
            {"token_symbol": "USDT", "network_short": "TRC20", "wallet_address": "T123"},
        ]
        count = store.add_wallets_bulk(scan_id, wallets)
        assert count == 3
        assert len(store.get_wallets(scan_id)) == 3


class TestGetWallets:
    """Tests for SsiStore.get_wallets."""

    def test_empty_scan_returns_empty(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)
        scan_id = store.create_scan(url="https://example.com")
        assert store.get_wallets(scan_id) == []


class TestSearchWallets:
    """Tests for SsiStore.search_wallets."""

    def _seed_wallets(self, store: SsiStore) -> tuple[str, str]:
        """Seed two scans with overlapping wallets."""
        sid1 = store.create_scan(url="https://scam1.com")
        sid2 = store.create_scan(url="https://scam2.com")
        store.add_wallet(scan_id=sid1, token_symbol="ETH", network_short="ERC20", wallet_address="0xAAA", confidence=0.5)
        store.add_wallet(scan_id=sid2, token_symbol="ETH", network_short="ERC20", wallet_address="0xAAA", confidence=0.8)
        store.add_wallet(scan_id=sid1, token_symbol="BTC", network_short="BTC", wallet_address="1btc")
        return sid1, sid2

    def test_search_all_deduplicated(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)
        self._seed_wallets(store)
        results = store.search_wallets()
        # 2 unique addresses: 0xAAA and 1btc
        assert len(results) == 2

    def test_search_dedup_includes_seen_count(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)
        self._seed_wallets(store)
        results = store.search_wallets(address="0xAAA")
        assert len(results) == 1
        assert results[0]["seen_count"] == 2
        assert float(results[0]["confidence"]) == 0.8  # max

    def test_search_by_token_symbol(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)
        self._seed_wallets(store)
        results = store.search_wallets(token_symbol="btc")
        assert len(results) == 1
        assert results[0]["wallet_address"] == "1btc"

    def test_search_no_dedup(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)
        self._seed_wallets(store)
        results = store.search_wallets(deduplicate=False)
        # 3 total rows (0xAAA appears in two scans + 1btc)
        assert len(results) == 3

    def test_search_limit(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)
        self._seed_wallets(store)
        results = store.search_wallets(limit=1)
        assert len(results) == 1


# ---------------------------------------------------------------------------
# agent_sessions tests
# ---------------------------------------------------------------------------


class TestLogAgentAction:
    """Tests for SsiStore.log_agent_action."""

    def test_log_returns_session_id(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)
        scan_id = store.create_scan(url="https://example.com")
        session_id = store.log_agent_action(
            scan_id=scan_id,
            state="completed",
            sequence=0,
            action_type="navigate",
        )
        assert session_id
        assert isinstance(session_id, str)

    def test_log_full_action(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)
        scan_id = store.create_scan(url="https://example.com")
        store.log_agent_action(
            scan_id=scan_id,
            state="completed",
            sequence=1,
            action_type="click",
            action_detail={"element_index": 5, "text": "Submit"},
            screenshot_path="/tmp/screenshot_1.png",
            page_url="https://example.com/form",
            dom_confidence=0.92,
            llm_model="gemini-2.0-flash",
            llm_input_tokens=500,
            llm_output_tokens=100,
            cost_usd=0.001,
            duration_ms=1500,
            metadata={"step": "fill_form"},
        )
        actions = store.get_agent_actions(scan_id)
        assert len(actions) == 1
        a = actions[0]
        assert a["action_type"] == "click"
        assert a["dom_confidence"] is not None
        assert a["duration_ms"] == 1500

    def test_log_error_action(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)
        scan_id = store.create_scan(url="https://example.com")
        store.log_agent_action(
            scan_id=scan_id,
            state="error",
            sequence=0,
            error="Element not found",
        )
        actions = store.get_agent_actions(scan_id)
        assert actions[0]["state"] == "error"
        assert actions[0]["error"] == "Element not found"

    def test_duration_ms_float_cast(self, tmp_path: object) -> None:
        """duration_ms accepts float and casts to int."""
        store = _make_store(tmp_path)
        scan_id = store.create_scan(url="https://example.com")
        store.log_agent_action(
            scan_id=scan_id,
            state="completed",
            sequence=0,
            duration_ms=1234.56,
        )
        actions = store.get_agent_actions(scan_id)
        assert actions[0]["duration_ms"] == 1234


class TestGetAgentActions:
    """Tests for SsiStore.get_agent_actions."""

    def test_empty_returns_empty(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)
        scan_id = store.create_scan(url="https://example.com")
        assert store.get_agent_actions(scan_id) == []

    def test_ordered_by_sequence(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)
        scan_id = store.create_scan(url="https://example.com")
        store.log_agent_action(scan_id=scan_id, state="completed", sequence=2)
        store.log_agent_action(scan_id=scan_id, state="completed", sequence=0)
        store.log_agent_action(scan_id=scan_id, state="completed", sequence=1)
        actions = store.get_agent_actions(scan_id)
        sequences = [a["sequence"] for a in actions]
        assert sequences == [0, 1, 2]


# ---------------------------------------------------------------------------
# pii_exposures tests
# ---------------------------------------------------------------------------


class TestAddPiiExposure:
    """Tests for SsiStore.add_pii_exposure."""

    def test_add_returns_exposure_id(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)
        scan_id = store.create_scan(url="https://example.com")
        exposure_id = store.add_pii_exposure(
            scan_id=scan_id,
            field_type="email",
        )
        assert exposure_id
        assert isinstance(exposure_id, str)

    def test_add_full_exposure(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)
        scan_id = store.create_scan(url="https://example.com")
        store.add_pii_exposure(
            scan_id=scan_id,
            field_type="password",
            field_label="Password",
            form_action="https://example.com/login",
            page_url="https://example.com/login",
            is_required=True,
            was_submitted=True,
            case_id="case-001",
            metadata={"notes": "plaintext password field"},
        )
        exposures = store.get_pii_exposures(scan_id)
        assert len(exposures) == 1
        e = exposures[0]
        assert e["field_type"] == "password"
        assert e["field_label"] == "Password"
        assert e["is_required"] is True
        assert e["was_submitted"] is True


class TestAddPiiExposuresBulk:
    """Tests for SsiStore.add_pii_exposures_bulk."""

    def test_bulk_empty_returns_zero(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)
        scan_id = store.create_scan(url="https://example.com")
        assert store.add_pii_exposures_bulk(scan_id, []) == 0

    def test_bulk_insert_multiple(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)
        scan_id = store.create_scan(url="https://example.com")
        exposures = [
            {"field_type": "email", "field_label": "Email"},
            {"field_type": "password", "field_label": "Password"},
            {"field_type": "phone", "field_label": "Phone Number"},
        ]
        count = store.add_pii_exposures_bulk(scan_id, exposures)
        assert count == 3
        assert len(store.get_pii_exposures(scan_id)) == 3


class TestGetPiiExposures:
    """Tests for SsiStore.get_pii_exposures."""

    def test_empty_returns_empty(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)
        scan_id = store.create_scan(url="https://example.com")
        assert store.get_pii_exposures(scan_id) == []


# ---------------------------------------------------------------------------
# Cross-table integration tests
# ---------------------------------------------------------------------------


class TestFullInvestigationWorkflow:
    """End-to-end workflow: create scan → add wallets + actions + PII → complete."""

    def test_full_lifecycle(self, tmp_path: object) -> None:
        store = _make_store(tmp_path)

        # Create scan
        scan_id = store.create_scan(
            url="https://fake-crypto-exchange.com",
            scan_type="full",
            domain="fake-crypto-exchange.com",
        )
        assert store.get_scan(scan_id)["status"] == "running"

        # Add wallets
        store.add_wallets_bulk(scan_id, [
            {"token_symbol": "ETH", "network_short": "ERC20", "wallet_address": "0x111"},
            {"token_symbol": "BTC", "network_short": "BTC", "wallet_address": "1btc"},
        ])
        assert len(store.get_wallets(scan_id)) == 2

        # Add agent actions
        store.log_agent_action(scan_id=scan_id, state="completed", sequence=0, action_type="navigate")
        store.log_agent_action(scan_id=scan_id, state="completed", sequence=1, action_type="click")
        store.log_agent_action(scan_id=scan_id, state="completed", sequence=2, action_type="extract")
        assert len(store.get_agent_actions(scan_id)) == 3

        # Add PII exposures
        store.add_pii_exposures_bulk(scan_id, [
            {"field_type": "email"},
            {"field_type": "password"},
        ])
        assert len(store.get_pii_exposures(scan_id)) == 2

        # Complete scan
        store.complete_scan(
            scan_id,
            status="completed",
            risk_score=87.5,
            wallet_count=2,
            duration_seconds=30.0,
        )
        final = store.get_scan(scan_id)
        assert final["status"] == "completed"
        assert float(final["risk_score"]) == 87.5
        assert final["wallet_count"] == 2
        assert final["completed_at"] is not None

        # Verify listing
        scans = store.list_scans(status="completed")
        assert len(scans) == 1
        assert scans[0]["scan_id"] == scan_id

    def test_multiple_scans_isolated(self, tmp_path: object) -> None:
        """Wallets/actions/PII from different scans don't bleed."""
        store = _make_store(tmp_path)

        sid1 = store.create_scan(url="https://scam1.com")
        sid2 = store.create_scan(url="https://scam2.com")

        store.add_wallet(scan_id=sid1, token_symbol="ETH", network_short="ERC20", wallet_address="0x1")
        store.add_wallet(scan_id=sid2, token_symbol="BTC", network_short="BTC", wallet_address="1b")

        store.log_agent_action(scan_id=sid1, state="completed", sequence=0)
        store.add_pii_exposure(scan_id=sid2, field_type="email")

        assert len(store.get_wallets(sid1)) == 1
        assert len(store.get_wallets(sid2)) == 1
        assert len(store.get_agent_actions(sid1)) == 1
        assert len(store.get_agent_actions(sid2)) == 0
        assert len(store.get_pii_exposures(sid1)) == 0
        assert len(store.get_pii_exposures(sid2)) == 1
