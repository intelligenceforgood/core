"""Shared bootstrap logic."""

from __future__ import annotations

import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class VerificationReport:
    environment: str
    timestamp: str
    bundles: dict[str, Any]
    storage: dict[str, Any]
    smoke_tests: dict[str, Any]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SmokeResult:
    status: str
    message: str


@dataclass
class DossierSmokeResult:
    status: str
    message: str
    plan_id: str | None = None
    manifest_path: str | None = None
    signature_path: str | None = None


@dataclass
class SearchSmokeResult:
    status: str
    message: str


def get_bundles() -> dict[str, str]:
    run_date = os.getenv("RUN_DATE", "2025-12-17")

    # Golden bundle is the default.  Legacy bundles are only used as fallback
    # when the golden bundle is not present on GCS.
    return {
        "golden": f"gs://i4g-dev-data-bundles/{run_date}/golden",
    }


def run_search_smoke(
    *,
    smoke_search: bool = False,
    run_search_smoke: bool = False,
    search_project: str | None = None,
    search_data_store_id: str | None = None,
    search_serving_config_id: str | None = None,
    search_location: str | None = None,
    search_query: str = "wallet address verification",
    search_page_size: int = 5,
) -> SearchSmokeResult:
    """Run a lightweight Vertex search smoke when requested."""

    if not smoke_search and not run_search_smoke:
        return SearchSmokeResult(status="skipped", message="Search smoke disabled.")

    project = search_project or os.getenv("I4G_VECTOR__VERTEX_AI_PROJECT") or os.getenv("I4G_PROJECT")
    data_store = search_data_store_id or os.getenv("I4G_VECTOR__VERTEX_AI_DATA_STORE")
    serving_config = search_serving_config_id or os.getenv("I4G_VECTOR__VERTEX_AI_SERVING_CONFIG")
    location = search_location or os.getenv("I4G_VECTOR__VERTEX_AI_LOCATION") or "global"

    if not project or not data_store or not serving_config:
        return SearchSmokeResult(
            status="skipped",
            message="Missing search configuration (project/data_store/serving_config).",
        )

    try:
        from i4g.cli.smoke import runner as smoke_runner

        smoke_runner.vertex_search_smoke(
            project=project,
            location=location,
            data_store_id=data_store,
            serving_config_id=serving_config,
            query=search_query,
            page_size=search_page_size,
        )
    except SystemExit as exc:  # pragma: no cover - subprocess failure path
        return SearchSmokeResult(status="failed", message=str(exc))
    except Exception as exc:  # pragma: no cover - safety net
        return SearchSmokeResult(status="failed", message=str(exc))

    return SearchSmokeResult(status="success", message="Vertex search returned results.")


def run_dossier_smoke(
    *,
    smoke_dossiers: bool = False,
    run_dossier_smoke: bool = False,
    smoke_api_url: str | None = None,
    smoke_token: str | None = None,
    smoke_dossier_status: str = "completed",
    smoke_dossier_limit: int = 5,
    smoke_dossier_plan_id: str | None = None,
) -> DossierSmokeResult:
    """Run dossier signature verification smoke when requested."""

    if not smoke_dossiers and not run_dossier_smoke:
        return DossierSmokeResult(status="skipped", message="Dossier smoke disabled.")

    try:
        from i4g.cli.smoke import dossiers

        result = dossiers.run_smoke(
            api_url=smoke_api_url,
            token=smoke_token,
            status=smoke_dossier_status,
            limit=smoke_dossier_limit,
            plan_id=smoke_dossier_plan_id,
            iap_token=None,
        )
    except Exception as exc:  # pragma: no cover - CLI/network boundary safety net
        return DossierSmokeResult(status="failed", message=str(exc))

    return DossierSmokeResult(
        status="success",
        message="Dossier verification passed.",
        plan_id=str(result.plan_id) if getattr(result, "plan_id", None) else None,
        manifest_path=str(result.manifest_path) if getattr(result, "manifest_path", None) else None,
        signature_path=str(result.signature_path) if getattr(result, "signature_path", None) else None,
    )


def run(cmd: list[str], env_overrides: dict[str, str] | None = None) -> None:
    """Run a subprocess command."""
    subprocess.run(cmd, check=True, env=env_overrides)


def download_bundles(bundles_dir: Path) -> None:
    """Download all data bundles from GCS if missing."""
    for name, uri in get_bundles().items():
        target_dir = bundles_dir / name
        if target_dir.exists() and any(target_dir.iterdir()):
            print(f"✅ Bundle {name} already present.")
            continue

        target_dir.mkdir(parents=True, exist_ok=True)
        print(f"⬇️  Downloading {name} from {uri}...")
        try:
            subprocess.run(["gcloud", "storage", "cp", "-r", uri, str(target_dir)], check=True)
        except subprocess.CalledProcessError:
            run_date = os.getenv("RUN_DATE", "2025-12-17")
            print(f"❌ Failed to download bundle '{name}' from {uri}")
            print(f"   RUN_DATE={run_date!r} — verify this date exists on GCS:")
            print(f"   gcloud storage ls gs://i4g-dev-data-bundles/{run_date}/")
            print("   Also ensure gcloud auth is active: gcloud auth application-default login")
            raise SystemExit(1) from None
        except Exception as exc:
            print(f"❌ Unexpected error downloading bundle '{name}': {exc}")
            raise SystemExit(1) from None
