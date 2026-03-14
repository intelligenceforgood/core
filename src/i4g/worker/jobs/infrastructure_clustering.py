"""Infrastructure clustering job — discovers shared-hosting relationships.

Queries entity co-occurrence patterns across cases to find infrastructure
links (shared IP, shared registrar, shared hosting provider) and writes
edges to the ``infrastructure_edges`` table.

Run manually::

    i4g jobs infrastructure-clustering

Or schedule via ``I4G_ANALYTICS__INFRASTRUCTURE_CLUSTERING_INTERVAL_HOURS``.
"""

from __future__ import annotations

import logging
import sys
import uuid
from collections import defaultdict
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from i4g.store.sql import (
    dialect_insert,
    entities,
    infrastructure_edges,
)
from i4g.store.sql import session_factory as build_sql_session_factory
from i4g.worker.logging import configure_job_logging

logger = logging.getLogger(__name__)

# Edge types discovered by this job
SHARED_CASE = "shared_case"
SHARED_IP = "shared_ip"
SHARED_REGISTRAR = "shared_registrar"
SHARED_HOSTING = "shared_hosting"

# Entity types that imply infrastructure relationships
_INFRA_ENTITY_TYPES = frozenset(
    {
        "ip_address",
        "domain",
        "url",
        "email_domain",
        "registrar",
        "hosting_provider",
        "nameserver",
    }
)

# Minimum co-occurrence count to create an edge
_MIN_COOCCURRENCE = 2


def run_infrastructure_clustering(*, min_cooccurrence: int = _MIN_COOCCURRENCE) -> int:
    """Execute one pass of infrastructure clustering.

    Groups entities that share cases and creates edges between them
    when they co-occur above the threshold.

    Args:
        min_cooccurrence: Minimum number of shared cases to create an edge.

    Returns:
        Number of new edges inserted.
    """
    sf = build_sql_session_factory()
    session: Session = sf()
    try:
        return _compute_and_store_edges(session, min_cooccurrence)
    finally:
        session.close()


def _compute_and_store_edges(session: Session, min_cooccurrence: int) -> int:
    """Compute co-occurrence and upsert infrastructure edges.

    Args:
        session: Active database session.
        min_cooccurrence: Minimum co-occurrences required.

    Returns:
        Number of edges inserted/updated.
    """
    # Step 1: Build entity→cases mapping for infrastructure entity types
    stmt = sa.select(
        entities.c.entity_type,
        entities.c.canonical_value,
        entities.c.case_id,
    ).where(
        entities.c.entity_type.in_(list(_INFRA_ENTITY_TYPES)),
    )
    rows = session.execute(stmt).fetchall()

    if not rows:
        logger.info("No infrastructure entities found — nothing to cluster")
        return 0

    # Group by case_id → list of (entity_type, canonical_value) tuples
    case_entities: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for row in rows:
        case_entities[row.case_id].append((row.entity_type, row.canonical_value))

    # Step 2: Count pairwise co-occurrences
    pair_count: dict[tuple[tuple[str, str], tuple[str, str]], int] = defaultdict(int)
    pair_cases: dict[tuple[tuple[str, str], tuple[str, str]], list[str]] = defaultdict(list)

    for case_id, ents in case_entities.items():
        # Deduplicate entities within a single case
        unique_ents = sorted(set(ents))
        for i in range(len(unique_ents)):
            for j in range(i + 1, len(unique_ents)):
                key = (unique_ents[i], unique_ents[j])
                pair_count[key] += 1
                pair_cases[key].append(case_id)

    # Step 3: Filter by threshold and classify edge types
    edges_inserted = 0
    now = datetime.now(UTC)
    insert_fn = dialect_insert(session, infrastructure_edges)

    for (src, tgt), count in pair_count.items():
        if count < min_cooccurrence:
            continue

        src_type, src_value = src
        tgt_type, tgt_value = tgt
        edge_type = _classify_edge_type(src_type, tgt_type)
        confidence = min(1.0, count / 10.0)  # Scale: 2→0.2, 5→0.5, 10+→1.0

        edge_id = str(uuid.uuid4())
        values = {
            "edge_id": edge_id,
            "source_entity_type": src_type,
            "source_canonical_value": src_value,
            "target_entity_type": tgt_type,
            "target_canonical_value": tgt_value,
            "edge_type": edge_type,
            "confidence": confidence,
            "evidence": {"shared_case_count": count, "case_ids": pair_cases[(src, tgt)][:50]},
            "discovered_at": now,
        }

        # Upsert: update confidence and evidence if edge already exists
        stmt = insert_fn.values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["edge_id"],
            set_={
                "confidence": confidence,
                "evidence": values["evidence"],
                "discovered_at": now,
            },
        )
        session.execute(stmt)
        edges_inserted += 1

    session.commit()
    logger.info("Infrastructure clustering: %d edge(s) upserted", edges_inserted)
    return edges_inserted


def _classify_edge_type(src_type: str, tgt_type: str) -> str:
    """Classify the edge type based on entity types.

    Args:
        src_type: Source entity type.
        tgt_type: Target entity type.

    Returns:
        Infrastructure edge type label.
    """
    types = {src_type, tgt_type}
    if "ip_address" in types:
        return SHARED_IP
    if "registrar" in types:
        return SHARED_REGISTRAR
    if "hosting_provider" in types or "nameserver" in types:
        return SHARED_HOSTING
    return SHARED_CASE


def main() -> int:
    """Entry point for the infrastructure clustering job."""
    configure_job_logging()
    logger.info("Starting infrastructure clustering job")
    try:
        count = run_infrastructure_clustering()
        logger.info("Infrastructure clustering complete — %d edge(s)", count)
        return 0
    except Exception:
        logger.exception("Infrastructure clustering job failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
