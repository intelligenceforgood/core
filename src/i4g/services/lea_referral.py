"""LEA referral suggestion engine.

Surfaces prompts when entities or campaigns meet threshold criteria for
law enforcement agency referral: >$50K cumulative loss, >5 linked cases,
or eCrimeX corroboration. Analysts can then compile an LEA Evidence Dossier.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from i4g.store.analytics_store import AnalyticsStore
from i4g.store.threat_campaign_store import ThreatCampaignStore

logger = logging.getLogger(__name__)

# Default thresholds — can be overridden via settings
DEFAULT_LOSS_THRESHOLD = 50_000.0
DEFAULT_MIN_CASES = 5


@dataclass(frozen=True)
class LeaSuggestion:
    """A single LEA referral suggestion."""

    suggestion_id: str
    target_type: str  # "entity" or "campaign"
    target_id: str
    target_label: str
    reasons: list[str]
    loss_sum: float = 0.0
    case_count: int = 0
    risk_score: float = 0.0
    ecx_corroborated: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "suggestion_id": self.suggestion_id,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "target_label": self.target_label,
            "reasons": self.reasons,
            "loss_sum": self.loss_sum,
            "case_count": self.case_count,
            "risk_score": self.risk_score,
            "ecx_corroborated": self.ecx_corroborated,
        }


class LeaReferralEngine:
    """Evaluates entities and campaigns against LEA referral thresholds.

    Args:
        analytics_store: Pre-computed analytics data.
        campaign_store: Threat campaign store.
        loss_threshold: Minimum cumulative loss (USD) to trigger suggestion.
        min_cases: Minimum linked case count to trigger suggestion.
    """

    def __init__(
        self,
        analytics_store: AnalyticsStore,
        campaign_store: ThreatCampaignStore,
        *,
        loss_threshold: float = DEFAULT_LOSS_THRESHOLD,
        min_cases: int = DEFAULT_MIN_CASES,
    ) -> None:
        self._analytics = analytics_store
        self._campaigns = campaign_store
        self._loss_threshold = loss_threshold
        self._min_cases = min_cases

    def get_suggestions(self, *, limit: int = 20) -> list[LeaSuggestion]:
        """Evaluate all entities and campaigns and return those meeting LEA thresholds.

        A target qualifies if ANY of the following are true:
        - Cumulative loss exceeds ``loss_threshold``
        - Linked case count exceeds ``min_cases``
        - eCrimeX corroboration is present

        Args:
            limit: Maximum number of suggestions to return.

        Returns:
            List of LEA referral suggestions, sorted by loss descending.
        """
        suggestions: list[LeaSuggestion] = []

        # Evaluate entities
        entities = self._analytics.list_entity_stats(limit=5000)
        for ent in entities:
            reasons = self._evaluate_entity(ent)
            if reasons:
                suggestions.append(
                    LeaSuggestion(
                        suggestion_id=f"entity:{ent.get('entity_type', '')}:{ent.get('canonical_value', '')}",
                        target_type="entity",
                        target_id=f"{ent.get('entity_type', '')}:{ent.get('canonical_value', '')}",
                        target_label=ent.get("canonical_value", ""),
                        reasons=reasons,
                        loss_sum=float(ent.get("loss_sum", 0)),
                        case_count=int(ent.get("case_count", 0)),
                        risk_score=float(ent.get("max_risk_score", 0)),
                        ecx_corroborated=bool(ent.get("ecx_hit")),
                    )
                )

        # Evaluate campaigns
        campaigns = self._campaigns.list_campaigns(limit=500)
        for camp in campaigns:
            cid = camp.get("campaign_id", "")
            stat = self._analytics.get_campaign_stat(cid) or {}
            reasons = self._evaluate_campaign(camp, stat)
            if reasons:
                suggestions.append(
                    LeaSuggestion(
                        suggestion_id=f"campaign:{cid}",
                        target_type="campaign",
                        target_id=cid,
                        target_label=camp.get("name", ""),
                        reasons=reasons,
                        loss_sum=float(stat.get("loss_sum", 0)),
                        case_count=int(stat.get("case_count", 0)),
                        risk_score=float(camp.get("risk_score") or stat.get("risk_score", 0)),
                    )
                )

        # Sort by loss descending, cap at limit
        suggestions.sort(key=lambda s: s.loss_sum, reverse=True)
        return suggestions[:limit]

    def _evaluate_entity(self, entity: dict[str, Any]) -> list[str]:
        """Check if an entity meets any LEA referral threshold.

        Args:
            entity: Entity stats dict.

        Returns:
            List of reason strings (empty if no threshold met).
        """
        reasons: list[str] = []
        loss = float(entity.get("loss_sum", 0))
        case_count = int(entity.get("case_count", 0))

        if loss >= self._loss_threshold:
            reasons.append(f"Cumulative loss ${loss:,.0f} exceeds ${self._loss_threshold:,.0f} threshold")
        if case_count >= self._min_cases:
            reasons.append(f"{case_count} linked cases (threshold: {self._min_cases})")
        if entity.get("ecx_hit"):
            reasons.append("Corroborated by eCrimeX partner reports")
        return reasons

    def _evaluate_campaign(self, campaign: dict[str, Any], stat: dict[str, Any]) -> list[str]:
        """Check if a campaign meets any LEA referral threshold.

        Args:
            campaign: Campaign metadata dict.
            stat: Pre-computed campaign stats dict.

        Returns:
            List of reason strings (empty if no threshold met).
        """
        reasons: list[str] = []
        loss = float(stat.get("loss_sum", 0))
        case_count = int(stat.get("case_count", 0))

        if loss >= self._loss_threshold:
            reasons.append(f"Campaign loss ${loss:,.0f} exceeds ${self._loss_threshold:,.0f} threshold")
        if case_count >= self._min_cases:
            reasons.append(f"{case_count} linked cases (threshold: {self._min_cases})")
        return reasons
