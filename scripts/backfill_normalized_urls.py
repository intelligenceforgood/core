"""Backfill site_scans.normalized_url from existing url column.

Reads all ``site_scans`` rows where ``normalized_url IS NULL`` and
``url IS NOT NULL``, computes the canonical form, and updates the row.
Batches updates in groups of 100 rows per transaction.

Usage:
    conda run -n i4g python scripts/backfill_normalized_urls.py [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import sys

import sqlalchemy as sa

from i4g.store.sql import session_factory, site_scans
from i4g.utils.url_normalization import normalize_url

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BATCH_SIZE = 100


def backfill(*, dry_run: bool = False) -> int:
    """Populate site_scans.normalized_url for rows that lack it.

    Args:
        dry_run: If True, report count without updating.

    Returns:
        Number of rows updated (or that would be updated in dry-run mode).
    """
    factory = session_factory()

    with factory() as session:
        rows = session.execute(
            sa.select(site_scans.c.scan_id, site_scans.c.url).where(
                site_scans.c.normalized_url.is_(None),
                site_scans.c.url.isnot(None),
            )
        ).fetchall()

        total = len(rows)
        logger.info("Found %d site_scans rows needing normalized_url", total)

        if dry_run:
            logger.info("[DRY RUN] Would update %d rows", total)
            return total

        updated = 0
        for i, row in enumerate(rows, 1):
            normalized = normalize_url(row.url)
            session.execute(
                sa.update(site_scans).where(site_scans.c.scan_id == row.scan_id).values(normalized_url=normalized)
            )
            updated += 1

            if i % BATCH_SIZE == 0:
                session.commit()
                logger.info("Progress: %d / %d rows processed", i, total)

        session.commit()
        logger.info("Backfill complete: updated %d rows with normalized_url", updated)
        return updated


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Backfill site_scans.normalized_url")
    parser.add_argument("--dry-run", action="store_true", help="Report count without updating")
    args = parser.parse_args()

    count = backfill(dry_run=args.dry_run)
    sys.exit(0 if count >= 0 else 1)


if __name__ == "__main__":
    main()
