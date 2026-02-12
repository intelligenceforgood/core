"""Helpers that prepare agent-friendly dossier payloads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from i4g.reports.bundle_builder import DossierPlan
from i4g.reports.dossier_analysis import DossierAnalysis
from i4g.reports.dossier_context import DossierContextResult


@dataclass(frozen=True)
class DossierAgentPayload:
    """Container passed into the LangChain-based dossier agent."""

    plan: dict[str, Any]
    context: dict[str, Any] | None
    analysis: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan,
            "context": self.context,
            "analysis": self.analysis,
        }


def build_agent_payload(
    *,
    plan: DossierPlan,
    context: DossierContextResult | None,
    analysis: DossierAnalysis,
) -> DossierAgentPayload:
    """Return a serializable agent payload combining plan, context, and analysis."""

    return DossierAgentPayload(
        plan=plan.to_dict(),
        context=context.to_dict() if context else None,
        analysis=analysis.to_dict(),
    )


__all__ = ["DossierAgentPayload", "build_agent_payload"]
