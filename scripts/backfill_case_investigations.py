"""Backfill case_investigations from existing site_scans.case_id FK.

Reads all ``site_scans`` rows that have a non-NULL ``case_id`` and inserts
matching rows into the ``case_investigations`` join table with
``trigger_type='case_created'``.  Uses ``INSERT ... ON CONFLICT DO NOTHING``
so the script is safe to re-run.

Usage:
    conda run -n i4g python scripts/backfill_case_investigations.py [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import sys

import sqlalchemy as sa

from i4g.store.sql import case_investigations, session_factory, site_scans

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def backfill(*, dry_run: bool = False) -> int:
    """Populate case_investigations from existing site_scans.case_id links.

    Args:
        dry_run: If True, report count without inserting.

    Returns:
        Number of rows inserted (or that would be inserted in dry-run mode).
    """
    factory = session_factory()

    with factory() as session:
        rows = session.execute(
            sa.select(site_scans.c.scan_id, site_scans.c.case_id).where(site_scans.c.case_id.isnot(None))
        ).fetchall()

        total = len(rows)
        logger.info("Found %d site_scans rows with case_id set", total)

        if dry_run:
            logger.info("[DRY RUN] Would insert %d rows into case_investigations", total)
            return total

        inserted = 0
        dialect_name = session.get_bind().dialect.name
        for i, row in enumerate(rows, 1):
            if dialect_name == "postgresql":
                from sqlalchemy.dialects.postgresql import insert as pg_insert

                stmt = (
                    pg_insert(case_investigations)
                    .values(
                        case_id=row.case_id,
                        scan_id=row.scan_id,
                        trigger_type="case_created",
                    )
                    .on_conflict_do_nothing()
                )
            else:
                from sqlalchemy.dialects.sqlite import insert as sqlite_insert

                stmt = (
                    sqlite_insert(case_investigations)
                    .values(
                        case_id=row.case_id,
                        scan_id=row.scan_id,
                        trigger_type="case_created",
                    )
                    .on_conflict_do_nothing()
                )
            session.execute(stmt)
            inserted += 1

            if i % 100 == 0:
                session.commit()
                logger.info("Progress: %d / %d rows processed", i, total)

        session.commit()
        logger.info("Backfill complete: inserted %d rows into case_investigations", inserted)
        return inserted


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Backfill case_investigations from site_scans.case_id")
    parser.add_argument("--dry-run", action="store_true", help="Report count without inserting")
    args = parser.parse_args()

    count = backfill(dry_run=args.dry_run)
    sys.exit(0 if count >= 0 else 1)


if __name__ == "__main__":
    main()
