"""Service for managing campaigns and mapping classifications to them."""

import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from i4g.store.sql import campaigns
from i4g.taxonomy.data import TAXONOMY_DEFINITIONS
from i4g.taxonomy.models import FraudClassificationResult


class CampaignService:
    """Service for Campaign management and resolution."""

    def __init__(self, session: Session):
        self.session = session

    def resolve_campaign(self, classification: FraudClassificationResult) -> str | None:
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

    def _matches_criteria(self, classification: FraudClassificationResult, criteria: dict[str, Any] | None) -> bool:
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

    def list_active_campaigns(self) -> list[dict[str, Any]]:
        """List all active campaigns with their basic info."""
        query = sa.select(campaigns).where(campaigns.c.status == "active")
        results = self.session.execute(query).fetchall()

        def _sanitize_labels(val: Any) -> dict[str, Any] | None:
            if isinstance(val, dict):
                return val
            # Handle case where JSON array [] is stored instead of null/dict
            if isinstance(val, list) and not val:
                return None
            return None

        def _sanitize_rollup(val: Any) -> list[str]:
            if not isinstance(val, list):
                return []
            # Ensure all elements are strings; filter out oddities
            return [str(x) for x in val if x is not None]

        return [
            {
                "id": row.campaign_id,
                "name": row.name,
                "description": row.description,
                "taxonomy_labels": _sanitize_labels(row.taxonomy_labels),
                "taxonomy_rollup": _sanitize_rollup(row.taxonomy_rollup),
            }
            for row in results
        ]

    def create_campaign(
        self,
        name: str,
        description: str,
        taxonomy_labels: dict[str, Any],
        associated_taxonomy_ids: list[str] | None = None,
    ) -> str:
        """Create a new campaign."""
        if associated_taxonomy_ids:
            self._validate_taxonomy_ids(associated_taxonomy_ids)
        else:
            associated_taxonomy_ids = []

        campaign_id = str(uuid.uuid4())
        stmt = sa.insert(campaigns).values(
            campaign_id=campaign_id,
            name=name,
            description=description,
            taxonomy_labels=taxonomy_labels,
            taxonomy_rollup=associated_taxonomy_ids,
            status="active",
        )
        self.session.execute(stmt)
        self.session.commit()
        return campaign_id

    def update_campaign(
        self,
        campaign_id: str,
        name: str | None = None,
        description: str | None = None,
        taxonomy_labels: dict[str, Any] | None = None,
        associated_taxonomy_ids: list[str] | None = None,
    ) -> None:
        """Update an existing campaign."""
        values: dict[str, Any] = {
            "updated_at": sa.func.now(),
        }
        if name is not None:
            values["name"] = name
        if description is not None:
            values["description"] = description
        if taxonomy_labels is not None:
            values["taxonomy_labels"] = taxonomy_labels
        if associated_taxonomy_ids is not None:
            self._validate_taxonomy_ids(associated_taxonomy_ids)
            values["taxonomy_rollup"] = associated_taxonomy_ids

        stmt = sa.update(campaigns).where(campaigns.c.campaign_id == campaign_id).values(**values)
        result = self.session.execute(stmt)
        self.session.commit()

        if result.rowcount == 0:
            raise ValueError(f"Campaign {campaign_id} not found.")

    def _validate_taxonomy_ids(self, taxonomy_ids: list[str]) -> None:
        """Validate that all taxonomy IDs exist in the current taxonomy tree."""
        valid_ids = self._get_all_taxonomy_ids()
        invalid_ids = set(taxonomy_ids) - valid_ids
        if invalid_ids:
            raise ValueError(f"Invalid taxonomy IDs: {invalid_ids}")

    def _get_all_taxonomy_ids(self) -> set[str]:
        """Traverse the taxonomy axes and collect all item codes."""
        ids = set()
        for axis in TAXONOMY_DEFINITIONS.get("axes", []):
            for item in axis.get("items", []):
                ids.add(item["code"])
        return ids
