"""CLI helper to verify dossier signature manifests against local artifacts.

Usage examples:
  conda run -n i4g python scripts/verify_dossier_hashes.py --path data/reports/dossiers
  conda run -n i4g python scripts/verify_dossier_hashes.py --path data/reports/dossiers/example.signatures.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, List, Sequence

from i4g.reports.dossier_signatures import ManifestVerificationReport, verify_manifest_file
from i4g.settings import get_settings


def _find_manifests(targets: Sequence[Path]) -> List[Path]:
    manifests: List[Path] = []
    for target in targets:
        if target.is_file() and target.name.endswith(".signatures.json"):
            manifests.append(target)
        elif target.is_dir():
            manifests.extend(sorted(target.rglob("*.signatures.json")))
    return manifests


def _verify_manifest(manifest_path: Path) -> ManifestVerificationReport:
    return verify_manifest_file(manifest_path)


def _summarize(manifest_path: Path, report: ManifestVerificationReport) -> str:
    status = "OK" if report.all_verified else "FAIL"
    missing = report.missing_count
    mismatch = report.mismatch_count
    return f"{status} {manifest_path} missing={missing} mismatch={mismatch} warnings={len(report.warnings)}"


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify dossier signature manifests")
    parser.add_argument(
        "--path",
        required=False,
        default=None,
        help="Path to a manifest file or directory (defaults to data/reports/dossiers)",
    )
    parser.add_argument(
        "--fail-on-warn",
        action="store_true",
        help="Exit non-zero when any manifest emits warnings",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    settings = get_settings()
    base_path = Path(args.path) if args.path else settings.data_dir / "reports" / "dossiers"
    targets = [base_path]
    manifests = _find_manifests(targets)
    if not manifests:
        print(f"No signature manifests found under {base_path}")
        return 1

    exit_code = 0
    for manifest in manifests:
        report = _verify_manifest(manifest)
        print(_summarize(manifest, report))
        if not report.all_verified:
            exit_code = 2
        if args.fail_on_warn and report.warnings:
            exit_code = max(exit_code, 3)
    return exit_code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
