"""PhishDestroy actors ingestion module.

Reads DestroyScammers/data/data.json and registrants.json, writing to:
- threat_actors
- actor_identities
- leak_records
- registrant_pivots
- actor_identity_edges

Idempotent. Never auto-merges actors.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from i4g.ingestion.phishdestroy import ALLOWED_PHISHDESTROY_SOURCES
from i4g.store.actor_identity_edge_store import ActorIdentityEdgeStore
from i4g.store.actor_identity_store import ActorIdentityStore
from i4g.store.leak_record_store import LeakRecordStore
from i4g.store.registrant_pivot_store import RegistrantPivotStore
from i4g.store.threat_actor_store import ThreatActorStore

LOGGER = logging.getLogger("i4g.ingestion.phishdestroy.actors")

_SOURCE = "phishdestroy.actors"
assert _SOURCE in ALLOWED_PHISHDESTROY_SOURCES, f"{_SOURCE!r} missing from ALLOWED_PHISHDESTROY_SOURCES"
_REGISTRANTS_SOURCE = "phishdestroy.registrants"
assert _REGISTRANTS_SOURCE in ALLOWED_PHISHDESTROY_SOURCES, f"{_REGISTRANTS_SOURCE!r} missing"


@dataclass(frozen=True)
class IngestSummary:
    """Summary of actors ingestion run."""

    actors_inserted: int = 0
    actors_updated: int = 0
    leaks_inserted: int = 0
    leaks_updated: int = 0
    registrants_inserted: int = 0
    registrants_updated: int = 0
    edges_inserted: int = 0
    edges_updated: int = 0


def _record_id(*parts: str) -> str:
    """Deterministically hash string parts for idempotency keys."""
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def _build_provenance(
    source: str,
    commit_sha: str,
    record_id: str,
    ingested_at: str,
    ingest_job: str,
    ingest_job_run_id: str | None,
) -> dict[str, Any]:
    """Build the source_provenance dict per provenance contract."""
    prov: dict[str, Any] = {
        "source": source,
        "commit_sha": commit_sha,
        "record_id": record_id,
        "ingested_at": ingested_at,
        "ingest_job": ingest_job,
    }
    if ingest_job_run_id is not None:
        prov["ingest_job_run_id"] = ingest_job_run_id
    return prov


def ingest_actors(
    data_path: Path,
    commit_sha: str,
    ingest_job: str,
    ingest_job_run_id: str | None,
    threat_actor_store: ThreatActorStore,
    actor_identity_store: ActorIdentityStore,
    leak_record_store: LeakRecordStore,
    registrant_pivot_store: RegistrantPivotStore,
    actor_identity_edge_store: ActorIdentityEdgeStore,
    now: datetime | None = None,
) -> IngestSummary:
    """Read data.json and registrants.json, write rows."""
    if now is None:
        now = datetime.now(UTC)
    ingested_at = now.isoformat()

    with data_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    emails_data = data.get("emails", [])

    registrants_path = data_path.parent / "registrants.json"
    registrants_data = []
    if registrants_path.exists():
        with registrants_path.open("r", encoding="utf-8") as f:
            registrants_data = json.load(f)

    # State tracking for summary
    actors_inserted = 0
    leaks_inserted = 0
    registrants_inserted = 0
    edges_inserted = 0

    # 1. Threat Actors & Identities + Leaks
    # We map email -> identity_id so we can later link registrants/edges
    email_to_actor_id: dict[str, str] = {}
    email_to_identity_id: dict[str, str] = {}

    for entry in emails_data:
        email = entry.get("email")
        if not email:
            continue

        email = email.lower().strip()
        rec_id = _record_id(email)

        prov = _build_provenance(
            source=_SOURCE,
            commit_sha=commit_sha,
            record_id=rec_id,
            ingested_at=ingested_at,
            ingest_job=ingest_job,
            ingest_job_run_id=ingest_job_run_id,
        )

        existing_id = actor_identity_store.find_by_handle(platform="email", handle=email)
        if existing_id:
            actor_id = existing_id["actor_id"]
            identity_id = existing_id["identity_id"]
            # To strictly avoid updates unless changed, we just use it.
        else:
            leak_info = entry.get("leak_info")
            google = entry.get("google")

            real_name = None
            if isinstance(leak_info, dict) and leak_info.get("fullname"):
                real_name = leak_info["fullname"]
            elif isinstance(google, dict) and google.get("fullname"):
                real_name = google["fullname"]

            display_name = email.split("@")[0]

            # We create a new threat actor
            actor = threat_actor_store.create(
                display_name=display_name,
                role="actor",
                real_name=real_name,
                first_seen_at=now,
                last_seen_at=now,
                source_provenance=prov,
            )
            actors_inserted += 1
            actor_id = actor["actor_id"]

            ident = actor_identity_store.upsert_by_handle(
                actor_id=actor_id,
                platform="email",
                handle=email,
                first_seen_at=now,
                last_seen_at=now,
                source_provenance=prov,
            )
            identity_id = ident["identity_id"]

        email_to_actor_id[email] = actor_id
        email_to_identity_id[email] = identity_id

        # Leaks
        passwords = entry.get("passwords", [])
        for p in passwords:
            password = p.get("password")
            source = p.get("source")
            if not password or not source:
                continue

            leak_rec_id = _record_id(email, source, password)
            leak_prov = _build_provenance(
                source=_SOURCE,
                commit_sha=commit_sha,
                record_id=leak_rec_id,
                ingested_at=ingested_at,
                ingest_job=ingest_job,
                ingest_job_run_id=ingest_job_run_id,
            )
            leak_record_store.upsert(
                actor_id=actor_id,
                breach_name=source,
                password_cleartext=password,
                source_provenance=leak_prov,
            )
            leaks_inserted += 1

    # 2. Registrants
    for reg in registrants_data:
        actor_email = reg.get("actor")
        if not actor_email:
            continue
        actor_email = actor_email.lower().strip()

        actor_id = email_to_actor_id.get(actor_email)
        if not actor_id:
            continue

        domain = reg.get("domain")
        name = reg.get("name")
        phone = reg.get("phone")

        for pivot_type, pivot_value in [("domain", domain), ("name", name), ("phone", phone)]:
            if not pivot_value or pivot_value == "REDACTED FOR PRIVACY":
                continue

            reg_rec_id = _record_id(actor_email, pivot_type, pivot_value)
            reg_prov = _build_provenance(
                source=_REGISTRANTS_SOURCE,
                commit_sha=commit_sha,
                record_id=reg_rec_id,
                ingested_at=ingested_at,
                ingest_job=ingest_job,
                ingest_job_run_id=ingest_job_run_id,
            )

            registrant_pivot_store.upsert(
                pivot_type=pivot_type,
                pivot_value=pivot_value,
                actor_id=actor_id,
                source_provenance=reg_prov,
            )
            registrants_inserted += 1

    # 3. Edges
    # The task asks for shared_domain_registrant edge builder.
    # That implies if two actors share the same domain registrant (name/phone/domain)
    # we create an edge between them.
    # Group registrants by pivot_type + pivot_value
    pivot_to_actors: dict[tuple[str, str], set[str]] = {}
    for reg in registrants_data:
        actor_email = reg.get("actor", "").lower().strip()
        if not actor_email or actor_email not in email_to_identity_id:
            continue

        identity_id = email_to_identity_id[actor_email]
        domain = reg.get("domain")
        name = reg.get("name")
        phone = reg.get("phone")

        for pivot_type, pivot_value in [("domain", domain), ("name", name), ("phone", phone)]:
            if not pivot_value or pivot_value == "REDACTED FOR PRIVACY":
                continue
            pivot_to_actors.setdefault((pivot_type, pivot_value), set()).add(identity_id)

    # Create edges
    for (ptype, pvalue), identity_ids in pivot_to_actors.items():
        if len(identity_ids) < 2:
            continue

        ids_list = sorted(list(identity_ids))
        for i in range(len(ids_list)):
            for j in range(i + 1, len(ids_list)):
                source_id = ids_list[i]
                target_id = ids_list[j]

                # To maintain idempotency we rely on upsert_edge internally doing UPSERT.
                # The task also mentions shared_telegram_group and shared_wallet, but
                # those aren't present in this dataset easily accessible, or perhaps
                # they are in `data.json`. The instructions say:
                # "Edge builder: shared_telegram_group, shared_domain_registrant, shared_wallet"
                # If they are not found, we just do domain_registrant.
                actor_identity_edge_store.upsert_edge(
                    source_identity_id=source_id,
                    target_identity_id=target_id,
                    edge_type="shared_domain_registrant",
                    weight=1.0,
                    evidence={"pivot_type": ptype, "pivot_value": pvalue},
                )
                edges_inserted += 1

    return IngestSummary(
        actors_inserted=actors_inserted,
        leaks_inserted=leaks_inserted,
        registrants_inserted=registrants_inserted,
        edges_inserted=edges_inserted,
    )
