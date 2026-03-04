"""Reports/dossier verification helpers."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from i4g.reports.dossier_signatures import verify_manifest_file
from i4g.settings import get_settings


def _find_manifests(targets: Sequence[Path]) -> list[Path]:
    manifests: list[Path] = []
    for target in targets:
        if target.is_file() and target.name.endswith(".signatures.json"):
            manifests.append(target)
        elif target.is_dir():
            manifests.extend(sorted(target.rglob("*.signatures.json")))
    return manifests


def verify_dossier_hashes(*, path: str | Path | None = None, fail_on_warn: bool = False) -> int:
    base_path = Path(path) if path else get_settings().data_dir / "reports" / "dossiers"
    targets = [base_path]
    manifests = _find_manifests(targets)
    if not manifests:
        print(f"No signature manifests found under {base_path}")
        return 1

    exit_code = 0
    for manifest in manifests:
        report = verify_manifest_file(manifest)
        status = "OK" if report.all_verified else "FAIL"
        missing = report.missing_count
        mismatch = report.mismatch_count
        summary = f"{status} {manifest} missing={missing} mismatch={mismatch} warnings={len(report.warnings)}"
        print(summary)
        if not report.all_verified:
            exit_code = 2
        if fail_on_warn and report.warnings:
            exit_code = max(exit_code, 3)
    return exit_code


def verify_ingestion_run(
    *,
    run_id: str | None = None,
    dataset: str | None = None,
    status: str = "succeeded",
    expect_case_count: int | None = None,
    min_case_count: int | None = None,
    expect_sql_writes: int | None = None,
    expect_vertex_writes: int | None = None,
    max_retry_count: int | None = None,
    require_vector_enabled: bool = False,
    allow_partial: bool = False,
    verbose: bool = False,
) -> int:
    import sqlalchemy as sa

    from i4g.store import sql as sql_schema
    from i4g.store.sql import build_engine

    resolved_settings = get_settings()
    engine = build_engine(settings=resolved_settings)

    stmt = sa.select(sql_schema.ingestion_runs)
    if run_id:
        stmt = stmt.where(sql_schema.ingestion_runs.c.run_id == run_id)
    if dataset:
        stmt = stmt.where(sql_schema.ingestion_runs.c.dataset == dataset)
    stmt = stmt.order_by(sql_schema.ingestion_runs.c.created_at.desc()).limit(1)

    with engine.connect() as conn:
        row = conn.execute(stmt).mappings().first()

    if row is None:
        target = run_id or dataset or "latest"
        raise SystemExit(f"No ingestion run found for target={target}")

    errors: list[str] = []
    row_status = row["status"]
    expected_status = status
    if allow_partial and expected_status == "succeeded":
        expected_status = "partial"
    if expected_status and row_status != expected_status:
        errors.append(f"status expected={expected_status} actual={row_status}")

    if expect_case_count is not None and row["case_count"] != expect_case_count:
        errors.append(f"case_count expected={expect_case_count} actual={row['case_count']}")
    if min_case_count is not None and row["case_count"] < min_case_count:
        errors.append(f"case_count minimum={min_case_count} actual={row['case_count']}")
    if expect_sql_writes is not None and row["sql_writes"] != expect_sql_writes:
        errors.append(f"sql_writes expected={expect_sql_writes} actual={row['sql_writes']}")
    if expect_vertex_writes is not None and row["vertex_writes"] != expect_vertex_writes:
        errors.append(f"vertex_writes expected={expect_vertex_writes} actual={row['vertex_writes']}")
    if max_retry_count is not None and row["retry_count"] > max_retry_count:
        errors.append(f"retry_count exceeded max={max_retry_count} actual={row['retry_count']}")
    if require_vector_enabled and not bool(row["vector_enabled"]):
        errors.append("vector_enabled expected=True actual=False")

    if errors:
        print("❌ Ingestion run validation failed:")
        for message in errors:
            print(f"  - {message}")
        return 1

    summary = (
        f"✅ run_id={row['run_id']} dataset={row['dataset']} status={row['status']} "
        f"cases={row['case_count']} sql={row['sql_writes']} "
        f"vertex={row['vertex_writes']} retries={row['retry_count']}"
    )
    print(summary)
    if verbose:
        print({key: row[key] for key in row})
    return 0


__all__ = ["verify_dossier_hashes", "verify_ingestion_run"]
