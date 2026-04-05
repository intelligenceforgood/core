"""Apply seed.sql from the golden bundle to the configured database backend."""

from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path

import sqlalchemy as sa
from google.cloud import storage

from i4g.store.sql import cases
from i4g.store.sql import session_factory as build_sql_session_factory

LOGGER = logging.getLogger(__name__)

_GOLDEN_SEED_BLOB = "golden/seed.sql"
_PLACEHOLDER_RE = re.compile(r"golden-case-\d{4}")


def _split_sql(sql: str) -> list[str]:
    """Split SQL text on semicolons, respecting single-quoted string literals."""
    statements: list[str] = []
    buf: list[str] = []
    in_string = False
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch == "'" and in_string:
            buf.append(ch)
            if i + 1 < len(sql) and sql[i + 1] == "'":
                buf.append("'")
                i += 1
            else:
                in_string = False
        elif ch == "'":
            in_string = True
            buf.append(ch)
        elif ch == ";" and not in_string:
            statements.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        statements.append("".join(buf))
    return statements


def _find_seed_sql_local() -> Path | None:
    """Search common local bundle locations for seed.sql."""
    from i4g.settings import get_settings

    settings = get_settings()
    project_root = settings.project_root

    candidates = [
        project_root / "data" / "bundles" / "golden" / "golden" / "seed.sql",
        project_root / "data" / "bundles" / "golden" / "seed.sql",
        project_root / "data" / "bundles" / "golden_seed" / "seed.sql",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _download_seed_sql_from_gcs(bucket_name: str, run_date: str) -> Path | None:
    """Download seed.sql from the golden bundle on GCS."""
    client = storage.Client()
    bucket = client.bucket(bucket_name)

    prefixes = [
        f"{run_date}/golden/seed.sql",
        f"{run_date}/golden/golden/seed.sql",
        "golden/seed.sql",
        "golden/golden/seed.sql",
    ]

    for prefix in prefixes:
        blob = bucket.blob(prefix)
        if blob.exists():
            with tempfile.NamedTemporaryFile(suffix=".sql", delete=False) as tmp:
                tmp_path = tmp.name
            blob.download_to_filename(tmp_path)
            LOGGER.info("Downloaded seed.sql from gs://%s/%s", bucket_name, prefix)
            return Path(tmp_path)

    LOGGER.warning("seed.sql not found in gs://%s under prefixes %s", bucket_name, prefixes)
    return None


def apply_seed_sql(
    *,
    gcs_bucket: str | None = None,
    run_date: str | None = None,
) -> int:
    """Apply seed.sql against the configured database.

    Reads seed.sql, replaces golden-case-XXXX placeholders with real case IDs
    from the cases table, and executes the SQL statements.

    Works with both SQLite and PostgreSQL (Cloud SQL).
    """
    import os

    # 1. Find seed.sql
    seed_path = _find_seed_sql_local()

    if not seed_path and gcs_bucket:
        date = run_date or os.getenv("RUN_DATE", "")
        seed_path = _download_seed_sql_from_gcs(gcs_bucket, date)

    if not seed_path:
        LOGGER.error("No seed.sql found locally or on GCS. Cannot apply seed data.")
        return 1

    LOGGER.info("Applying seed SQL from %s", seed_path)
    sql = seed_path.read_text(encoding="utf-8")

    # 2. Open DB session
    sf = build_sql_session_factory()
    session = sf()

    try:
        # 3. Gather real case IDs
        real_ids = [row[0] for row in session.execute(sa.select(cases.c.case_id).order_by(cases.c.case_id)).fetchall()]

        # 4. Replace placeholders
        placeholders = sorted(set(_PLACEHOLDER_RE.findall(sql)))
        if placeholders and real_ids:
            for i, ph in enumerate(placeholders):
                real = real_ids[i % len(real_ids)]
                sql = sql.replace(ph, real)
            LOGGER.info(
                "Replaced %d placeholder IDs with %d real case IDs.",
                len(placeholders),
                len(real_ids),
            )
        elif placeholders:
            LOGGER.error(
                "No real case IDs in DB; cannot resolve %d placeholder IDs. "
                "Run the ingestion job first to populate the cases table, "
                "then re-run seed SQL.",
                len(placeholders),
            )
            return 1

        # 5. Execute each statement
        executed = 0
        for statement in _split_sql(sql):
            statement = statement.strip()
            if not statement:
                continue
            # Skip pure comment blocks (keep statements that have inline comments above the SQL)
            lines = [ln.strip() for ln in statement.splitlines() if ln.strip() and not ln.strip().startswith("--")]
            if not lines:
                continue
            # Strip leading comment lines so sa.text() gets clean SQL
            clean = "\n".join(lines)
            try:
                session.execute(sa.text(clean))
                executed += 1
            except Exception:
                LOGGER.exception("Failed to execute seed SQL statement (first 120 chars): %s", statement[:120])
                raise

        session.commit()
        LOGGER.info("Seed SQL applied successfully (%d statements).", executed)
        return 0
    except Exception:
        session.rollback()
        LOGGER.exception("Seed SQL application failed; rolled back.")
        return 1
    finally:
        session.close()
