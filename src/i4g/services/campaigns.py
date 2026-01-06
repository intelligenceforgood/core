"""Service for managing campaigns and mapping classifications to them."""

import uuid
from typing import Any, Dict, Optional

import sqlalchemy as sa
from sqlalchemy.orm import Session

from i4g.store.sql import campaigns
from i4g.taxonomy.models import FraudClassificationResult


class CampaignService:
    """Service for Campaign management and resolution."""

    def __init__(self, session: Session):
        self.session = session

    def resolve_campaign(self, classification: FraudClassificationResult) -> Optional[str]:
        """
        Attempt to map a classification result to an existing campaign.
        Returns the campaign_id if a match is found.

        Logic:
        Iterates through active campaigns and checks if the classification
        contains ALL the labels defined in the campaign's taxonomy_labels.
        """
        # Fetch active campaigns
        # Note: In a production scenario with many campaigns, we might want to cache this
        # or optimize the query.
        query = sa.select(campaigns).where(campaigns.c.status == "active")
        active_campaigns = self.session.execute(query).fetchall()

        for campaign in active_campaigns:
            if self._matches_criteria(classification, campaign.taxonomy_labels):
                return campaign.campaign_id

        return None

    def _matches_criteria(self, classification: FraudClassificationResult, criteria: Dict[str, Any] | None) -> bool:
        """
        Check if the classification matches the campaign criteria.
        Criteria is expected to be a dict like:
        {
            "intent": ["INTENT.INVESTMENT"],
            "actions": ["ACTION.CRYPTO"]
        }
        """
        if not criteria:
            return False

        # Check intent
        if "intent" in criteria:
            required_intents = set(criteria["intent"])
            found_intents = {item.label for item in classification.intent}
            if not required_intents.issubset(found_intents):
                return False

        # Check actions
        if "actions" in criteria:
            required_actions = set(criteria["actions"])
            found_actions = {item.label for item in classification.actions}
            if not required_actions.issubset(found_actions):
                return False

        # Check techniques
        if "techniques" in criteria:
            required_techniques = set(criteria["techniques"])
            found_techniques = {item.label for item in classification.techniques}
            if not required_techniques.issubset(found_techniques):
                return False

        # Check channels
        if "channel" in criteria:
            required_channels = set(criteria["channel"])
            found_channels = {item.label for item in classification.channel}
            if not required_channels.issubset(found_channels):
                return False

        return True

    def list_active_campaigns(self) -> list[Dict[str, Any]]:
        """List all active campaigns with their basic info."""
        query = sa.select(campaigns).where(campaigns.c.status == "active")
        results = self.session.execute(query).fetchall()
        return [
            {
                "id": row.campaign_id,
                "name": row.name,
                "description": row.description,
                "taxonomy_labels": row.taxonomy_labels,
            }
            for row in results
        ]

    def create_campaign(self, name: str, description: str, taxonomy_labels: Dict[str, Any]) -> str:
        """Create a new campaign."""
        campaign_id = str(uuid.uuid4())
        stmt = sa.insert(campaigns).values(
            campaign_id=campaign_id,
            name=name,
            description=description,
            taxonomy_labels=taxonomy_labels,
            status="active",
        )
        self.session.execute(stmt)
        self.session.commit()
        return campaign_id
