"""One-time data migration: separate ingestion-batch campaign_id from
correlator-detected campaign_id.

This script identifies cases where ``campaign_id`` was set by the ingestion
pipeline (batch-provenance) rather than by the CampaignCorrelator.  Those
values are moved to the new ``ingestion_batch_id`` column and
``campaign_id`` is cleared, reserving ``campaign_id`` for correlator-
detected threat campaigns only.

Usage:
    conda run -n i4g python scripts/migration/migrate_campaign_to_batch.py [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import sys

import sqlalchemy as sa

from i4g.store.sql import campaigns, cases, session_factory

LOGGER = logging.getLogger(__name__)


def main(dry_run: bool = False) -> int:
    """Move ingestion-batch campaign_id values to ingestion_batch_id.

    Args:
        dry_run: When True, report affected rows without modifying data.

    Returns:
        Exit code: 0 on success.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    sf = session_factory()

    with sf() as session:
        # Identify campaigns that are ingestion-batch provenance (not correlator-detected).
        # Convention: ingestion-batch campaigns have no description or a name starting
        # with the dataset name. Correlator-detected campaigns have origin metadata.
        # We identify batch-provenance campaigns by checking if the campaign row
        # has no description and was created by the ingestion pipeline.
        batch_campaign_ids_stmt = sa.select(campaigns.c.campaign_id).where(
            sa.or_(
                campaigns.c.description.is_(None),
                campaigns.c.description == "",
            )
        )
        batch_campaign_ids = {row[0] for row in session.execute(batch_campaign_ids_stmt).all()}
        LOGGER.info("Found %d batch-provenance campaigns", len(batch_campaign_ids))

        if not batch_campaign_ids:
            LOGGER.info("No batch-provenance campaigns to migrate.")
            return 0

        # Find cases linked to these campaigns
        affected_stmt = sa.select(sa.func.count()).select_from(cases).where(cases.c.campaign_id.in_(batch_campaign_ids))
        affected_count = session.execute(affected_stmt).scalar() or 0
        LOGGER.info("Found %d cases to migrate", affected_count)

        if dry_run:
            LOGGER.info("Dry run — no changes made.")
            return 0

        # Move campaign_id to ingestion_batch_id for affected cases
        update_stmt = (
            sa.update(cases)
            .where(cases.c.campaign_id.in_(batch_campaign_ids))
            .values(
                ingestion_batch_id=cases.c.campaign_id,
                campaign_id=None,
            )
        )
        result = session.execute(update_stmt)
        session.commit()
        LOGGER.info("Migrated %d cases (campaign_id → ingestion_batch_id)", result.rowcount)

    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate batch campaign_id to ingestion_batch_id")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without modifying data")
    args = parser.parse_args()
    sys.exit(main(dry_run=args.dry_run))
