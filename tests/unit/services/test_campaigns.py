"""Unit tests for CampaignService."""

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from i4g.services.campaigns import CampaignService
from i4g.store.sql import campaigns, METADATA


@pytest.fixture
def db_session():
    """Create an in-memory SQLite session for testing."""
    engine = sa.create_engine("sqlite:///:memory:")
    METADATA.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_create_campaign_success(db_session):
    """Test creating a campaign with valid taxonomy linkage."""
    service = CampaignService(db_session)
    valid_id = "tax-trafficking"  # Known ID from taxonomy/data.py

    campaign_id = service.create_campaign(
        name="Test Campaign",
        description="A test campaign",
        taxonomy_labels={"intent": ["INTENT.ROMANCE"]},
        associated_taxonomy_ids=[valid_id],
    )

    assert campaign_id is not None

    # Verify fetching it back
    stmt = sa.select(campaigns).where(campaigns.c.campaign_id == campaign_id)
    row = db_session.execute(stmt).fetchone()

    assert row.name == "Test Campaign"
    assert row.status == "active"
    # In SQLite, SQLAlchemy JSON type should deserialize to a list
    assert row.taxonomy_rollup == [valid_id]


def test_create_campaign_invalid_rollup(db_session):
    """Test that creating a campaign with invalid taxonomy IDs raises ValueError."""
    service = CampaignService(db_session)

    with pytest.raises(ValueError, match="Invalid taxonomy IDs"):
        service.create_campaign(
            name="Bad Campaign", description="Should fail", taxonomy_labels={}, associated_taxonomy_ids=["fake-node-id"]
        )


def test_list_active_campaigns(db_session):
    """Test listing campaigns includes the rollup field."""
    service = CampaignService(db_session)

    # Create two campaigns
    c1 = service.create_campaign("C1", "D1", {}, ["tax-financial"])
    c2 = service.create_campaign("C2", "D2", {}, [])

    results = service.list_active_campaigns()

    assert len(results) == 2

    r1 = next(r for r in results if r["id"] == c1)
    assert r1["taxonomy_rollup"] == ["tax-financial"]

    r2 = next(r for r in results if r["id"] == c2)
    assert r2["taxonomy_rollup"] == []


def test_update_campaign(db_session):
    """Test updating campaign rollup."""
    service = CampaignService(db_session)
    c_id = service.create_campaign("Update Me", "Original", {}, [])

    # Update with valid ID
    service.update_campaign(c_id, associated_taxonomy_ids=["tax-intake"])

    stmt = sa.select(campaigns).where(campaigns.c.campaign_id == c_id)
    row = db_session.execute(stmt).fetchone()
    assert row.taxonomy_rollup == ["tax-intake"]

    # Update with Invalid ID should fail
    with pytest.raises(ValueError, match="Invalid taxonomy IDs"):
        service.update_campaign(c_id, associated_taxonomy_ids=["bad-id"])
