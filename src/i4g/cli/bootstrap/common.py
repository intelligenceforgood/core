"""Shared bootstrap logic."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional, List, Dict


@dataclass
class VerificationReport:
    environment: str
    timestamp: str
    bundles: Dict[str, Any]
    storage: Dict[str, Any]
    smoke_tests: Dict[str, Any]
    errors: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SmokeResult:
    status: str
    message: str


@dataclass
class DossierSmokeResult:
    status: str
    message: str
    plan_id: Optional[str] = None
    manifest_path: Optional[str] = None
    signature_path: Optional[str] = None


@dataclass
class SearchSmokeResult:
    status: str
    message: str


def get_bundles() -> dict[str, str]:
    run_date = os.getenv("RUN_DATE", "2025-12-17")

    return {
        "legacy_azure": f"gs://i4g-dev-data-bundles/{run_date}/legacy_azure/search_exports/vertex/",
        "public_scams": f"gs://i4g-dev-data-bundles/{run_date}/public_scams/cases.jsonl",
        "retrieval_poc": f"gs://i4g-dev-data-bundles/{run_date}/retrieval_poc/cases.jsonl",
        "synthetic_coverage": f"gs://i4g-dev-data-bundles/{run_date}/synthetic_coverage/full/cases.jsonl",
    }


def run_search_smoke(args: argparse.Namespace) -> SearchSmokeResult:
    """Run a lightweight Vertex search smoke when requested."""

    if not getattr(args, "smoke_search", False) and not getattr(args, "run_search_smoke", False):
        return SearchSmokeResult(status="skipped", message="Search smoke disabled.")

    project = (
        getattr(args, "search_project", None) or os.getenv("I4G_VECTOR__VERTEX_AI_PROJECT") or os.getenv("I4G_PROJECT")
    )
    data_store = getattr(args, "search_data_store_id", None) or os.getenv("I4G_VECTOR__VERTEX_AI_DATA_STORE")
    serving_config = getattr(args, "search_serving_config_id", None) or os.getenv(
        "I4G_VECTOR__VERTEX_AI_SERVING_CONFIG"
    )
    location = getattr(args, "search_location", None) or os.getenv("I4G_VECTOR__VERTEX_AI_LOCATION") or "global"

    if not project or not data_store or not serving_config:
        return SearchSmokeResult(
            status="skipped",
            message="Missing search configuration (project/data_store/serving_config).",
        )

    try:
        from i4g.cli import smoke

        search_args = SimpleNamespace(
            project=project,
            location=location,
            data_store_id=data_store,
            serving_config_id=serving_config,
            query=getattr(args, "search_query", "wallet address verification"),
            page_size=getattr(args, "search_page_size", 5),
        )
        smoke.vertex_search_smoke(search_args)
    except SystemExit as exc:  # pragma: no cover - subprocess failure path
        return SearchSmokeResult(status="failed", message=str(exc))
    except Exception as exc:  # pragma: no cover - safety net
        return SearchSmokeResult(status="failed", message=str(exc))

    return SearchSmokeResult(status="success", message="Vertex search returned results.")


def run_dossier_smoke(args: argparse.Namespace) -> DossierSmokeResult:
    """Run dossier signature verification smoke when requested."""

    if not getattr(args, "smoke_dossiers", False) and not getattr(args, "run_dossier_smoke", False):
        return DossierSmokeResult(status="skipped", message="Dossier smoke disabled.")

    try:
        from scripts import smoke_dossiers

        smoke_args = SimpleNamespace(
            api_url=getattr(args, "smoke_api_url", None),
            token=getattr(args, "smoke_token", None),
            status=getattr(args, "smoke_dossier_status", "completed"),
            limit=getattr(args, "smoke_dossier_limit", 5),
            plan_id=getattr(args, "smoke_dossier_plan_id", None),
        )
        result = smoke_dossiers.run_smoke(smoke_args)
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
        except Exception:
            print(f"⚠️  Failed to download {name}. Ensure you have gcloud auth and permissions.")
