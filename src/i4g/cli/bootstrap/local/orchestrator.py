"""Orchestrator for the local bootstrap flow."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from i4g.cli.admin.seed import seed_campaigns
from i4g.cli.bootstrap.common import download_bundles as common_download_bundles
from i4g.cli.bootstrap.common import (
    run_dossier_smoke,
    run_search_smoke,
)
from i4g.cli.utils import stage_bundle

from .constants import BUNDLES_DIR, DATA_DIR
from .steps import (
    apply_migrations,
    apply_seed_sql,
    ensure_dirs,
    ensure_pilot_cases_file,
    ingest_bundles,
    rebuild_manual_demo,
    reset_artifacts,
    run_ocr,
    run_semantic_extraction,
    seed_review_cases,
    stage_ocr_images,
)
from .verify import verify_sandbox


def run_local(
    *,
    reset: bool,
    skip_vector: bool,
    bundle_uri: str | None,
    dry_run: bool,
    verify_only: bool,
    report_dir: Path,
    smoke_search: bool,
    search_project: str | None,
    search_location: str | None,
    search_data_store_id: str | None,
    search_serving_config_id: str,
    search_query: str,
    search_page_size: int,
    smoke_dossiers: bool,
    smoke_api_url: str | None,
    smoke_token: str | None,
    smoke_dossier_status: str,
    smoke_dossier_limit: int,
    smoke_dossier_plan_id: str | None,
    force: bool,
    skip_ingest: bool = False,
    limit: int | None = None,
) -> None:
    """Execute the local sandbox bootstrap flow."""

    env_val = os.getenv("I4G_ENV", "")
    if env_val != "local" and not force:
        print(f"❌ Refusing to run: I4G_ENV={env_val!r} (expected 'local'). Pass --force to override.")
        return
    if env_val != "local":
        print(f"⚠️  Running with I4G_ENV={env_val!r}; proceeding due to --force.")

    if dry_run:
        print(
            f"[dry-run] Would reset={reset} skip_vector={skip_vector} bundle_uri={bundle_uri} verify_only={verify_only}"
        )
        return

    ensure_dirs()
    common_download_bundles(BUNDLES_DIR)

    if reset:
        reset_artifacts(skip_vector=skip_vector)

    if bundle_uri:
        stage_bundle(bundle_uri, BUNDLES_DIR)

    if verify_only:
        search_smoke = run_search_smoke(
            smoke_search=smoke_search,
            search_project=search_project,
            search_location=search_location,
            search_data_store_id=search_data_store_id,
            search_serving_config_id=search_serving_config_id,
            search_query=search_query,
            search_page_size=search_page_size,
        )
        if search_smoke.status == "failed":
            raise SystemExit(search_smoke.message)
        dossier_smoke = run_dossier_smoke(
            smoke_dossiers=smoke_dossiers,
            smoke_api_url=smoke_api_url,
            smoke_token=smoke_token,
            smoke_dossier_status=smoke_dossier_status,
            smoke_dossier_limit=smoke_dossier_limit,
            smoke_dossier_plan_id=smoke_dossier_plan_id,
        )
        if dossier_smoke.status == "failed":
            raise SystemExit(dossier_smoke.message)
        verify_sandbox(report_dir, search_smoke, dossier_smoke)
        return

    apply_migrations()
    seed_campaigns()

    if not skip_ingest:
        ingest_bundles(skip_vector=skip_vector, limit=limit)
    else:
        print("⚠️  Skipping bundle ingestion as requested.")

    apply_seed_sql()

    tesseract_available = shutil.which("tesseract") is not None
    if tesseract_available:
        stage_ocr_images()
        run_ocr()
        run_semantic_extraction()
    else:
        print(
            "⚠️  Tesseract not found on PATH; skipping OCR and semantic extraction. "
            "Install it to enable OCR testing."
        )

    if not skip_vector:
        rebuild_manual_demo()
    else:
        print("⚠️  Skipping vector/structured demo rebuild; existing stores assumed valid.")

    ensure_pilot_cases_file()
    seed_campaigns()
    seed_review_cases()

    search_smoke = run_search_smoke(
        smoke_search=smoke_search,
        search_project=search_project,
        search_location=search_location,
        search_data_store_id=search_data_store_id,
        search_serving_config_id=search_serving_config_id,
        search_query=search_query,
        search_page_size=search_page_size,
    )
    if search_smoke.status == "failed":
        raise SystemExit(search_smoke.message)
    dossier_smoke = run_dossier_smoke(
        smoke_dossiers=smoke_dossiers,
        smoke_api_url=smoke_api_url,
        smoke_token=smoke_token,
        smoke_dossier_status=smoke_dossier_status,
        smoke_dossier_limit=smoke_dossier_limit,
        smoke_dossier_plan_id=smoke_dossier_plan_id,
    )
    if dossier_smoke.status == "failed":
        raise SystemExit(dossier_smoke.message)
    verify_sandbox(report_dir, search_smoke, dossier_smoke)

    print("✅ Local sandbox refreshed. Data directory:", DATA_DIR)


__all__ = ["run_local"]
