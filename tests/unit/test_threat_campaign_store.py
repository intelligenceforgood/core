"""Unit tests for ThreatCampaignStore CRUD, merge, and split operations."""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from i4g.store.sql import METADATA
from i4g.store.threat_campaign_store import ThreatCampaignStore


def _make_store(db_path: Path) -> ThreatCampaignStore:
    """Build a ThreatCampaignStore backed by a temporary SQLite file."""
    engine = sa.create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    METADATA.create_all(engine)
    sf = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return ThreatCampaignStore(session_factory=sf)


def test_table_initialization(tmp_path: Path) -> None:
    """Tables are created when the store is initialized."""
    _make_store(tmp_path / "tc.db")


def test_create_and_get_campaign(tmp_path: Path) -> None:
    """Campaigns can be created and retrieved."""
    store = _make_store(tmp_path / "tc.db")

    cid = store.create_campaign(
        name="Test Campaign",
        description="A test campaign",
        origin="manual",
        created_by="analyst@test.com",
    )
    assert cid

    campaign = store.get_campaign(cid)
    assert campaign is not None
    assert campaign["name"] == "Test Campaign"
    assert campaign["description"] == "A test campaign"
    assert campaign["origin"] == "manual"
    assert campaign["status"] == "emerging"
    assert campaign["created_by"] == "analyst@test.com"


def test_list_campaigns(tmp_path: Path) -> None:
    """Lists campaigns with optional status filter."""
    store = _make_store(tmp_path / "tc.db")

    cid1 = store.create_campaign(name="Campaign 1")
    store.create_campaign(name="Campaign 2")

    all_campaigns = store.list_campaigns()
    assert len(all_campaigns) == 2

    store.update_status(cid1, status="active")
    active = store.list_campaigns(status="active")
    assert len(active) == 1
    assert active[0]["campaign_id"] == cid1


def test_update_status(tmp_path: Path) -> None:
    """Campaign status can be updated."""
    store = _make_store(tmp_path / "tc.db")

    cid = store.create_campaign(name="Status Test")
    assert store.get_campaign(cid)["status"] == "emerging"

    store.update_status(cid, status="active")
    assert store.get_campaign(cid)["status"] == "active"


def test_update_campaign(tmp_path: Path) -> None:
    """Campaign fields can be updated."""
    store = _make_store(tmp_path / "tc.db")

    cid = store.create_campaign(name="Original Name")
    store.update_campaign(cid, name="Updated Name", description="New description")

    campaign = store.get_campaign(cid)
    assert campaign["name"] == "Updated Name"
    assert campaign["description"] == "New description"


def test_link_and_unlink_case(tmp_path: Path) -> None:
    """Cases can be linked and unlinked from campaigns."""
    store = _make_store(tmp_path / "tc.db")

    cid = store.create_campaign(name="Link Test")

    # Need a case in the cases table first
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'tc.db'}")
    with engine.connect() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO cases (case_id, dataset, source_type, raw_text_sha256, status) "
                "VALUES ('case-1', 'test', 'reactive', 'abc123', 'open')"
            )
        )
        conn.commit()

    store.link_case(cid, "case-1", linked_by="analyst", link_reason="test link")

    cases = store.get_campaign_cases(cid)
    assert len(cases) == 1
    assert cases[0]["case_id"] == "case-1"

    # Verify reverse lookup
    campaigns = store.get_case_campaigns("case-1")
    assert len(campaigns) == 1
    assert campaigns[0]["campaign_id"] == cid

    store.unlink_case(cid, "case-1")
    assert len(store.get_campaign_cases(cid)) == 0


def test_merge_campaigns(tmp_path: Path) -> None:
    """Two campaigns can be merged into the primary one."""
    store = _make_store(tmp_path / "tc.db")

    primary = store.create_campaign(name="Primary")
    secondary = store.create_campaign(name="Secondary")

    # Create cases
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'tc.db'}")
    with engine.connect() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO cases (case_id, dataset, source_type, raw_text_sha256, status) "
                "VALUES ('c1', 'test', 'reactive', 'h1', 'open')"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO cases (case_id, dataset, source_type, raw_text_sha256, status) "
                "VALUES ('c2', 'test', 'reactive', 'h2', 'open')"
            )
        )
        conn.commit()

    store.link_case(primary, "c1")
    store.link_case(secondary, "c2")

    merged_id = store.merge_campaigns([primary, secondary], target_name="Merged Campaign")

    # All cases should now be on the merged campaign
    cases = store.get_campaign_cases(merged_id)
    case_ids = {c["case_id"] for c in cases}
    assert case_ids == {"c1", "c2"}

    # Both source campaigns should be closed
    pri = store.get_campaign(primary)
    assert pri["status"] == "closed"
    sec = store.get_campaign(secondary)
    assert sec["status"] == "closed"


def test_split_campaign(tmp_path: Path) -> None:
    """A subset of cases can be split into a new campaign."""
    store = _make_store(tmp_path / "tc.db")

    original = store.create_campaign(name="Original")

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'tc.db'}")
    with engine.connect() as conn:
        for i in range(3):
            conn.execute(
                sa.text(
                    f"INSERT INTO cases (case_id, dataset, source_type, raw_text_sha256, status) "
                    f"VALUES ('cs{i}', 'test', 'reactive', 'hash{i}', 'open')"
                )
            )
        conn.commit()

    for i in range(3):
        store.link_case(original, f"cs{i}")

    result = store.split_campaign(
        original,
        case_groups={"Split Campaign": ["cs1", "cs2"]},
    )
    assert "Split Campaign" in result
    new_id = result["Split Campaign"]

    # Original is closed after split
    orig = store.get_campaign(original)
    assert orig["status"] == "closed"

    # New campaign has cs1, cs2
    new_cases = store.get_campaign_cases(new_id)
    new_case_ids = {c["case_id"] for c in new_cases}
    assert new_case_ids == {"cs1", "cs2"}


def test_get_nonexistent_campaign(tmp_path: Path) -> None:
    """Getting a non-existent campaign returns None."""
    store = _make_store(tmp_path / "tc.db")
    assert store.get_campaign("nonexistent") is None
