"""PhishDestroy destroylist ingestion module.

Reads DestroyScammers/data/data.json and writes idempotent blocklist_hits rows
with source = "phishdestroy.destroylist".

record_id rule: sha256(normalized_indicator).hexdigest()
Rationale: data.json is a JSON blob without stable line numbers. The domain is
the deterministic key; hashing it gives a stable, reproducible record_id
independent of line order changes across commits. (Provenance §2 documents this
choice in the record_id table for phishdestroy.destroylist.)
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
from i4g.store.blocklist_hit_store import BlocklistHitStore

LOGGER = logging.getLogger("i4g.ingestion.phishdestroy.destroylist")

# Canonical source identifier for this pipeline — imported from the package
# vocabulary so the literal only lives in one place.
_SOURCE = "phishdestroy.destroylist"
assert _SOURCE in ALLOWED_PHISHDESTROY_SOURCES, f"{_SOURCE!r} missing from ALLOWED_PHISHDESTROY_SOURCES"

_MAX_ASSOCIATED_EMAILS = 50


@dataclass(frozen=True)
class IngestSummary:
    """Summary of a single destroylist ingestion run."""

    total_seen: int
    unique_domains: int
    rows_inserted: int
    rows_updated: int
    rows_unchanged: int


def _normalize(domain: str) -> str:
    """Normalize a domain: strip whitespace, lowercase."""
    return domain.strip().lower()


def _record_id(normalized_domain: str) -> str:
    """Stable record_id: sha256 of the normalized domain indicator (hex)."""
    return hashlib.sha256(normalized_domain.encode()).hexdigest()


def _build_provenance(
    *,
    normalized_domain: str,
    commit_sha: str,
    ingested_at: str,
    ingest_job: str,
    ingest_job_run_id: str | None,
) -> dict[str, Any]:
    """Build the source_provenance dict per §1 of the provenance contract."""
    prov: dict[str, Any] = {
        "source": _SOURCE,
        "commit_sha": commit_sha,
        "record_id": _record_id(normalized_domain),
        "ingested_at": ingested_at,
        "ingest_job": ingest_job,
    }
    if ingest_job_run_id is not None:
        prov["ingest_job_run_id"] = ingest_job_run_id
    return prov


def _provenance_matches(existing_prov: dict[str, Any] | None, new_prov: dict[str, Any]) -> bool:
    """Return True if the stored provenance is bit-identical to what would be written."""
    if existing_prov is None:
        return False
    # Compare only the stable fields; ingest_job_run_id may differ between runs
    # but commit_sha and record_id are the idempotency keys.
    return all(existing_prov.get(key) == new_prov.get(key) for key in ("source", "commit_sha", "record_id"))


def _metadata_matches(existing_meta: dict[str, Any] | None, new_meta: dict[str, Any]) -> bool:
    """Return True if the stored metadata is bit-identical to what would be written."""
    if existing_meta is None:
        return False
    return existing_meta.get("associated_emails") == new_meta.get("associated_emails")


def ingest_destroylist(
    *,
    data_path: Path,
    commit_sha: str,
    ingest_job: str,
    ingest_job_run_id: str | None = None,
    store: BlocklistHitStore,
    now: datetime | None = None,
) -> IngestSummary:
    """Read data.json and write idempotent blocklist_hits rows.

    Args:
        data_path: Path to DestroyScammers/data/data.json.
        commit_sha: Full 40-char hex SHA of the upstream DestroyScammers repo HEAD.
        ingest_job: Cloud Run job name or CLI command identifier.
        ingest_job_run_id: Cloud Run execution ID when available; None otherwise.
        store: BlocklistHitStore to upsert into.
        now: Timestamp to use for first_seen_at / last_seen_at / ingested_at.
             Defaults to UTC now at call time.

    Returns:
        IngestSummary with counts of rows inserted, updated, and unchanged.
    """
    if now is None:
        now = datetime.now(UTC)

    ingested_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Load and parse the JSON file.
    with data_path.open(encoding="utf-8") as fh:
        data = json.load(fh)

    # Build domain → sorted-deduped email list mapping.
    domain_to_emails: dict[str, list[str]] = {}
    total_seen = 0

    for entry in data.get("emails", []):
        email = entry.get("email", "")
        for raw_domain in entry.get("domains", []):
            if not isinstance(raw_domain, str):
                continue
            normalized = _normalize(raw_domain)
            if not normalized:
                continue
            total_seen += 1
            if normalized not in domain_to_emails:
                domain_to_emails[normalized] = []
            if email:
                domain_to_emails[normalized].append(email)

    # Deduplicate and sort email lists; cap at _MAX_ASSOCIATED_EMAILS.
    for domain in domain_to_emails:
        domain_to_emails[domain] = sorted(set(domain_to_emails[domain]))[:_MAX_ASSOCIATED_EMAILS]

    unique_domains = len(domain_to_emails)
    rows_inserted = 0
    rows_updated = 0
    rows_unchanged = 0

    for normalized_domain, emails in domain_to_emails.items():
        new_prov = _build_provenance(
            normalized_domain=normalized_domain,
            commit_sha=commit_sha,
            ingested_at=ingested_at,
            ingest_job=ingest_job,
            ingest_job_run_id=ingest_job_run_id,
        )
        new_meta: dict[str, Any] = {"associated_emails": emails}

        # Fetch existing row to decide whether to skip (idempotency).
        existing_rows = store.list_by_indicator(indicator_id=normalized_domain, limit=10)
        existing = next((r for r in existing_rows if r.get("source") == _SOURCE), None)

        if existing is not None:
            existing_prov = existing.get("source_provenance") or {}
            existing_meta = existing.get("metadata") or {}
            if _provenance_matches(existing_prov, new_prov) and _metadata_matches(existing_meta, new_meta):
                rows_unchanged += 1
                continue
            # Something changed — update.
            store.upsert(
                indicator_id=normalized_domain,
                source=_SOURCE,
                first_seen_at=existing.get("first_seen_at") or now,
                last_seen_at=now,
                metadata=new_meta,
                source_provenance=new_prov,
            )
            rows_updated += 1
        else:
            store.upsert(
                indicator_id=normalized_domain,
                source=_SOURCE,
                first_seen_at=now,
                last_seen_at=now,
                metadata=new_meta,
                source_provenance=new_prov,
            )
            rows_inserted += 1

    return IngestSummary(
        total_seen=total_seen,
        unique_domains=unique_domains,
        rows_inserted=rows_inserted,
        rows_updated=rows_updated,
        rows_unchanged=rows_unchanged,
    )
