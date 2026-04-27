"""TrustWalletPanel concrete adapter for the PhishDestroy ScamIntelLogs archive.

Implements the §"Adapter behaviour" contract from the Phase B manifest verbatim.

Phase C additions:
  - evidence_blob_sha256: populated in Phase C from chats_translated.json export blob.
  - infrastructure_profiles.metadata_json["evidence_blobs"]: list of photo / panel-capture /
    source-map evidence blobs persisted via ``storage/evidence.py``.

Phase D additions:
  - financial_damage_claims: parsed from successful_thefts/result.json via damage.py.
    TrustWalletPanel has no successful_thefts/ directory; all four financial_damage_claims_*
    counts are 0 in production TWP runs (no-op path).
  - brand_impersonations: best-effort write when indicators match panel_url via brands.py.
    Provenance reuses phishdestroy.archive.infrastructure.

Deferred writes (Sprint 3+):
  - actor_identities / threat_actors: Sprint 3 territory.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from i4g.ingestion.phishdestroy import ALLOWED_PHISHDESTROY_SOURCES
from i4g.ingestion.phishdestroy.archive.base import (
    ArchiveContext,
    build_chat_provenance,
    build_financial_damage_provenance,
    build_infra_provenance,
)
from i4g.ingestion.phishdestroy.archive.brands import lookup_indicators_for_domain
from i4g.ingestion.phishdestroy.archive.damage import parse_deposit_messages
from i4g.ingestion.phishdestroy.archive.evidence import persist_chat_export, persist_team_blobs
from i4g.ingestion.phishdestroy.archive.team_config import get_team_config

LOGGER = logging.getLogger("i4g.ingestion.phishdestroy.archive.trustwalletpanel")

_CHAT_SOURCE = "phishdestroy.archive.chat"
_INFRA_SOURCE = "phishdestroy.archive.infrastructure"
_DAMAGE_SOURCE = "phishdestroy.archive.financial_damage"

assert _CHAT_SOURCE in ALLOWED_PHISHDESTROY_SOURCES, f"{_CHAT_SOURCE!r} missing from ALLOWED_PHISHDESTROY_SOURCES"
assert _INFRA_SOURCE in ALLOWED_PHISHDESTROY_SOURCES, f"{_INFRA_SOURCE!r} missing from ALLOWED_PHISHDESTROY_SOURCES"
assert _DAMAGE_SOURCE in ALLOWED_PHISHDESTROY_SOURCES, f"{_DAMAGE_SOURCE!r} missing from ALLOWED_PHISHDESTROY_SOURCES"

# Language assumption: TrustWalletPanel chat archive is Russian.
# TODO(Phase D): replace hard-coded "ru" with language auto-detection.
_LANGUAGE = "ru"

_TEAM_NAME = "TrustWalletPanel"

# Module-scope team config lookup (Phase D). With TWP registered as equal to defaults,
# behaviour is byte-for-byte identical to Phase C.
_TEAM_CONFIG = get_team_config(_TEAM_NAME)


def _parse_metadata_dict(raw: Any) -> dict[str, Any]:
    """Normalise the metadata field, which may be a str or dict depending on dialect."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            result = json.loads(raw)
            return result if isinstance(result, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _find_or_create_campaign(ctx: ArchiveContext) -> str:
    """Return campaign_id for TrustWalletPanel, creating a row if none exists.

    Idempotency: queries all campaigns and returns the first whose metadata
    contains ``phishdestroy_team == "TrustWalletPanel"``.  This keeps the logic
    in the adapter rather than adding a store method (Phase B constraint).
    """
    all_campaigns = ctx.campaign_store.list_campaigns(limit=500)
    for camp in all_campaigns:
        meta = _parse_metadata_dict(camp.get("metadata"))
        if meta.get("phishdestroy_team") == _TEAM_NAME:
            LOGGER.debug("Reusing existing campaign_id=%s for team=%s", camp["campaign_id"], _TEAM_NAME)
            return camp["campaign_id"]

    campaign_id = ctx.campaign_store.create_campaign(
        name=_TEAM_NAME,
        origin="phishdestroy.archive",
        status="emerging",
        metadata={"phishdestroy_team": _TEAM_NAME},
    )
    LOGGER.info("Created new campaign_id=%s for team=%s", campaign_id, _TEAM_NAME)
    return campaign_id


def _ingest_infrastructure(
    team_dir: Path,
    iocs: dict[str, Any],
    campaign_id: str,
    ctx: ArchiveContext,
) -> dict[str, int]:
    """Ingest the infrastructure_profiles row from iocs.json.

    Returns counts dict with keys infra_inserted, infra_updated, infra_unchanged.
    """
    panel_url: str = iocs.get("panel_url", "")
    tech_stack: dict[str, Any] = iocs.get("tech_stack", {})

    auth_model: str | None = tech_stack.get("auth") or None
    cors_config: str | None = tech_stack.get("cors") or None

    admin_frontend: str = str(tech_stack.get("admin_frontend", ""))
    source_maps_exposed: bool = "source maps exposed" in admin_frontend.lower()

    metadata_json: dict[str, Any] = {
        "team_type": iocs.get("type"),
        "first_seen": iocs.get("first_seen"),
        "last_activity": iocs.get("last_activity"),
    }

    if ctx.evidence_storage is not None:
        blob_refs = persist_team_blobs(ctx.evidence_storage, _TEAM_NAME, team_dir, blob_config=_TEAM_CONFIG.blob_config)
        metadata_json["evidence_blobs"] = [ref.to_metadata_dict() for ref in blob_refs]

    record_id = f"{_TEAM_NAME}/iocs.json#/panel_url"
    provenance = build_infra_provenance(team=_TEAM_NAME, record_id=record_id, ctx=ctx)

    # Check for an existing row to determine insert vs update count.
    existing_profiles = ctx.infrastructure_profile_store.get_by_campaign(campaign_id)
    existing_profile = next(
        (p for p in existing_profiles if p.get("primary_domain") == panel_url),
        None,
    )

    ctx.infrastructure_profile_store.upsert_by_campaign_domain(
        campaign_id=campaign_id,
        primary_domain=panel_url,
        subdomain_roles=None,  # Phase D enrichment
        tech_stack=tech_stack,
        source_maps_exposed=source_maps_exposed,
        auth_model=auth_model,
        cors_config=cors_config,
        metadata_json=metadata_json,
        source_provenance=provenance,
    )

    # --- Phase D: brand impersonation best-effort writes -------------------------
    brand_impersonations_inserted = 0
    brand_impersonations_updated = 0
    brand_impersonations_skipped = 0

    if panel_url and _TEAM_CONFIG.brand is not None:
        try:
            indicator_ids = lookup_indicators_for_domain(
                ctx.chat_session_store._session_factory,  # noqa: SLF001
                panel_url,
            )
        except Exception:
            LOGGER.warning(
                "Brand indicator lookup failed for panel_url=%r; skipping brand impersonation writes",
                panel_url,
                exc_info=True,
            )
            indicator_ids = []

        for indicator_id in indicator_ids:
            bi_record_id = f"{_TEAM_NAME}/iocs.json#brand/{indicator_id}"
            bi_provenance = build_infra_provenance(team=_TEAM_NAME, record_id=bi_record_id, ctx=ctx)
            try:
                existing_rows = ctx.brand_impersonation_store.list_by_indicator(indicator_id)
                already_exists = any(r.get("brand") == _TEAM_CONFIG.brand for r in existing_rows)
                ctx.brand_impersonation_store.upsert_by_indicator_brand(
                    indicator_id=indicator_id,
                    brand=_TEAM_CONFIG.brand,
                    source_provenance=bi_provenance,
                )
                if already_exists:
                    brand_impersonations_updated += 1
                else:
                    brand_impersonations_inserted += 1
            except Exception:
                LOGGER.warning(
                    "Brand impersonation upsert failed for indicator_id=%r; skipping",
                    indicator_id,
                    exc_info=True,
                )
                brand_impersonations_skipped += 1

    if existing_profile is None:
        return {
            "infra_inserted": 1,
            "infra_updated": 0,
            "infra_unchanged": 0,
            "brand_impersonations_inserted": brand_impersonations_inserted,
            "brand_impersonations_updated": brand_impersonations_updated,
            "brand_impersonations_skipped": brand_impersonations_skipped,
        }

    # Row was pre-existing; the upsert refreshed it (count as updated).
    return {
        "infra_inserted": 0,
        "infra_updated": 1,
        "infra_unchanged": 0,
        "brand_impersonations_inserted": brand_impersonations_inserted,
        "brand_impersonations_updated": brand_impersonations_updated,
        "brand_impersonations_skipped": brand_impersonations_skipped,
    }


def _deposit_demand_heuristic(messages: list[dict[str, Any]]) -> bool:
    """Return True if any admin message contains OFAC/deposit/replacement keywords.

    Phase B coarse heuristic; Phase D will replace with LLM classification.
    """
    keywords = ("ofac", "deposit", "replacement")
    for msg in messages:
        if not msg.get("admin", False):
            continue
        text = (msg.get("text") or "").lower()
        if any(kw in text for kw in keywords):
            return True
    return False


def _ingest_chats(
    team_dir: Path,
    campaign_id: str,
    ctx: ArchiveContext,
) -> dict[str, int]:
    """Ingest chat sessions from chats_translated.json.

    Returns counts dict with keys chat_inserted, chat_updated, chat_unchanged.
    """
    chats_path = team_dir / "chats_translated.json"
    if not chats_path.exists():
        LOGGER.warning("chats_translated.json not found in %s; skipping chat ingestion", team_dir)
        return {"chat_inserted": 0, "chat_updated": 0, "chat_unchanged": 0}

    with chats_path.open(encoding="utf-8") as fh:
        entries = json.load(fh)

    if not isinstance(entries, list):
        LOGGER.error("chats_translated.json is not a JSON array in %s; skipping", team_dir)
        return {"chat_inserted": 0, "chat_updated": 0, "chat_unchanged": 0}

    # Build a set of record_ids already stored for this campaign so we can
    # accurately count inserts vs unchanged without an extra per-row query.
    existing_sessions = ctx.chat_session_store.list_by_campaign(campaign_id, limit=2000)
    existing_record_ids: set[str] = set()
    for sess in existing_sessions:
        prov = sess.get("source_provenance")
        if isinstance(prov, str):
            try:
                prov = json.loads(prov)
            except json.JSONDecodeError:
                prov = {}
        if isinstance(prov, dict):
            rid = prov.get("record_id")
            if rid:
                existing_record_ids.add(rid)

    chat_inserted = 0
    chat_updated = 0
    chat_unchanged = 0

    chat_blob_sha: str | None = None
    if ctx.evidence_storage is not None:
        result = persist_chat_export(ctx.evidence_storage, _TEAM_NAME, chats_path)
        if result is not None:
            chat_blob_sha, _ = result

    for idx, entry in enumerate(entries):
        entry_id = entry.get("id")
        if entry_id is None:
            # Missing 'id' — use array index as fallback (provenance §2).
            LOGGER.warning("Chat entry at index %d has no 'id'; using index as record_id suffix", idx)
            chat_ref = f"chats_translated.json#{idx}"
            record_id = f"{_TEAM_NAME}/chats_translated.json#{idx}"
        else:
            chat_ref = f"chats_translated.json#{entry_id}"
            record_id = f"{_TEAM_NAME}/chats_translated.json#{entry_id}"

        messages: list[dict[str, Any]] = entry.get("messages") or []
        message_count = len(messages)

        started_at: datetime | None = None
        last_message_at: datetime | None = None
        if messages:
            try:
                started_at = datetime.fromisoformat(messages[0]["date"])
            except (KeyError, ValueError, TypeError):
                LOGGER.warning("Could not parse started_at for entry %s", record_id)
            try:
                last_message_at = datetime.fromisoformat(messages[-1]["date"])
            except (KeyError, ValueError, TypeError):
                LOGGER.warning("Could not parse last_message_at for entry %s", record_id)

        deposit_demand = _deposit_demand_heuristic(messages)

        provenance = build_chat_provenance(team=_TEAM_NAME, record_id=record_id, ctx=ctx)

        ctx.chat_session_store.upsert_by_provenance(
            source_provenance=provenance,
            chat_ref=chat_ref,
            message_count=message_count,
            campaign_id=campaign_id,
            language=_LANGUAGE,
            deposit_demand=deposit_demand,
            victim_confirmed_send=False,  # Phase D
            started_at=started_at,
            last_message_at=last_message_at,
            evidence_blob_sha256=chat_blob_sha,
            case_id=None,  # Sprint 3
            actor_id=None,  # Sprint 3
        )

        if record_id in existing_record_ids:
            chat_unchanged += 1
        else:
            chat_inserted += 1

    return {"chat_inserted": chat_inserted, "chat_updated": chat_updated, "chat_unchanged": chat_unchanged}


def _ingest_successful_thefts(
    team_dir: Path,
    campaign_id: str,
    ctx: ArchiveContext,
) -> dict[str, int]:
    """Ingest financial damage records from successful_thefts/result.json (Phase D).

    Returns counts dict with keys:
    - financial_damage_claims_inserted
    - financial_damage_claims_updated
    - financial_damage_claims_unchanged
    - financial_damage_claims_skipped

    When result.json is absent the team has no recorded thefts; all counts are 0.
    """
    zero: dict[str, int] = {
        "financial_damage_claims_inserted": 0,
        "financial_damage_claims_updated": 0,
        "financial_damage_claims_unchanged": 0,
        "financial_damage_claims_skipped": 0,
    }

    result_path = team_dir / "successful_thefts" / "result.json"
    if not result_path.exists():
        return zero

    try:
        with result_path.open(encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError):
        LOGGER.error("Failed to read %s; skipping financial damage ingestion", result_path)
        return zero

    messages = raw.get("messages", []) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
    records, skipped = parse_deposit_messages(messages)

    # Pre-query existing provenance record_ids for this campaign to count inserts vs unchanged.
    existing_claims = ctx.financial_damage_store.list_by_campaign(campaign_id, limit=10000)
    existing_damage_record_ids: set[str] = set()
    for claim in existing_claims:
        prov = claim.get("source_provenance")
        if isinstance(prov, str):
            try:
                prov = json.loads(prov)
            except json.JSONDecodeError:
                prov = {}
        if isinstance(prov, dict) and prov.get("source") == _DAMAGE_SOURCE:
            rid = prov.get("record_id")
            if rid:
                existing_damage_record_ids.add(rid)

    inserted = 0
    updated = 0
    unchanged = 0

    for record in records:
        record_id = f"{_TEAM_NAME}/successful_thefts/result.json#{record.message_id}"
        provenance = build_financial_damage_provenance(team=_TEAM_NAME, record_id=record_id, ctx=ctx)
        metadata: dict[str, Any] = {"raw_text": record.raw_text}
        if record.project is not None:
            metadata["project"] = record.project
        if record.amount_usd_credited is not None:
            metadata["amount_usd_credited"] = str(record.amount_usd_credited)
        if record.operator_share_percent is not None:
            metadata["operator_share_percent"] = str(record.operator_share_percent)

        ctx.financial_damage_store.upsert_by_provenance(
            source_provenance=provenance,
            currency="USD",
            amount_claimed=record.amount_usd_claimed,
            campaign_id=campaign_id,
            chain=record.chain,
            metadata_json=metadata,
        )

        if record_id in existing_damage_record_ids:
            unchanged += 1
        else:
            inserted += 1

    return {
        "financial_damage_claims_inserted": inserted,
        "financial_damage_claims_updated": updated,
        "financial_damage_claims_unchanged": unchanged,
        "financial_damage_claims_skipped": skipped,
    }


class TrustWalletPanelAdapter:
    """Concrete adapter for the TrustWalletPanel scam-intelligence directory."""

    team_name: str = _TEAM_NAME

    def ingest(self, team_dir: Path, ctx: ArchiveContext) -> dict[str, int]:
        """Ingest TrustWalletPanel team directory.

        Args:
            team_dir: Absolute path to the TrustWalletPanel directory.
            ctx: Shared archive ingestion context.

        Returns:
            Flat counts dict matching the parse-failure report schema.
        """
        # Load iocs.json (format detector has already validated its presence).
        iocs_path = team_dir / "iocs.json"
        with iocs_path.open(encoding="utf-8") as fh:
            iocs: dict[str, Any] = json.load(fh)

        campaign_id = _find_or_create_campaign(ctx)

        infra_counts = _ingest_infrastructure(team_dir, iocs, campaign_id, ctx)
        chat_counts = _ingest_chats(team_dir, campaign_id, ctx)
        damage_counts = _ingest_successful_thefts(team_dir, campaign_id, ctx)

        return {
            "chat_sessions_inserted": chat_counts["chat_inserted"],
            "chat_sessions_updated": chat_counts["chat_updated"],
            "chat_sessions_unchanged": chat_counts["chat_unchanged"],
            "infrastructure_profiles_inserted": infra_counts["infra_inserted"],
            "infrastructure_profiles_updated": infra_counts["infra_updated"],
            "infrastructure_profiles_unchanged": infra_counts["infra_unchanged"],
            "financial_damage_claims_inserted": damage_counts["financial_damage_claims_inserted"],
            "financial_damage_claims_updated": damage_counts["financial_damage_claims_updated"],
            "financial_damage_claims_unchanged": damage_counts["financial_damage_claims_unchanged"],
            "financial_damage_claims_skipped": damage_counts["financial_damage_claims_skipped"],
            "brand_impersonations_inserted": infra_counts["brand_impersonations_inserted"],
            "brand_impersonations_updated": infra_counts["brand_impersonations_updated"],
            "brand_impersonations_skipped": infra_counts["brand_impersonations_skipped"],
        }
