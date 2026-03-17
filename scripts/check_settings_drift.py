#!/usr/bin/env python3
"""Check for drift between the Pydantic settings model, settings.default.toml, and settings_manifest.yaml.

Ensures every field declared in the Pydantic model has a corresponding entry
in ``config/settings.default.toml`` (active or commented) and in the settings
manifest (``docs/config/settings_manifest.yaml`` or ``../docs/config/settings_manifest.yaml``).

Exit codes:
    0 — all sources are in sync.
    1 — drift detected (missing entries printed to stderr).

Usage:
    python scripts/check_settings_drift.py          # from core/ repo root
    python scripts/check_settings_drift.py --fix     # regenerate manifest & print TOML stubs
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, get_origin

# ---------------------------------------------------------------------------
# Resolve paths relative to repo root (parent of this script's directory)
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_TOML = REPO_ROOT / "config" / "settings.default.toml"

# Manifest can live in core/docs/config/ or sibling docs/ repo
_MANIFEST_CANDIDATES = [
    REPO_ROOT / "docs" / "config" / "settings_manifest.yaml",
    REPO_ROOT.parent / "docs" / "config" / "settings_manifest.yaml",
]

# Fields on the Settings class that are not config keys (internal plumbing)
_INTERNAL_FIELDS = frozenset({"env_files", "config_files"})

# Top-level scalar fields that live outside any [section]
_TOP_LEVEL_SCALARS = frozenset({"env", "project_root", "data_dir"})

# Known drift that predates this check.  Remove entries as they are fixed.
# Each entry is a "section.field" path present in the model but intentionally
# not yet added to settings.default.toml or the manifest.
_TOML_ALLOWLIST: frozenset[str] = frozenset(
    {
        "analytics.campaign_risk_weights",
        "analytics.scheduled_report_max_consecutive_failures",
        "api.rate_limit_per_minute",
        "crypto.pii_key",
        "db_admin.dev_password",
        "db_admin.dev_vault_password",
        "db_admin.prod_password",
        "db_admin.prod_vault_password",
        "dossier_job.batch_size",
        "dossier_job.dry_run",
        "enrichment.blockchain_api_key",
        "enrichment.blockchain_vendor",
        "identity.iap_backend_audience",
        "ingest_retry_job.batch_limit",
        "ingest_retry_job.dry_run",
        "ingestion.default_service_account",
        "ingestion.enable_scheduled_jobs",
        "ingestion.fanout_timeout_seconds",
        "ingestion.max_retries",
        "ingestion.rate_limit_delay",
        "ingestion.retry_delay_seconds",
        "ingestion.skip_classification",
        "intake.api_base",
        "intake.api_key",
        "intake.id",
        "intake.job_id",
        "observability.detokenization_alert_threshold",
        "observability.dossier_stuck_timeout_minutes",
        "observability.ingestion_error_rate_threshold",
        "partner_feed.default_page_size",
        "partner_feed.enabled",
        "partner_feed.max_page_size",
        "partner_feed.rate_limit_per_minute",
        "redis.channel_prefix",
        "redis.poll_interval_seconds",
        "redis.url",
        "report.batch_limit",
        "report.dry_run",
        "report.review_ids",
        "report.target_status",
        "report.tool_timeout_seconds",
        "runtime.fallback_dir",
        "search.loss_buckets",
        "search.schema_cache_ttl_seconds",
        "search.schema_entity_example_limit",
        "smoke.api_url",
        "ssi.core_api_url",
        "ssi.events_endpoint",
        "ssi.playbook_dir",
        "ssi.service_url",
        "storage.report_bucket",
        "storage.ssi_evidence_bucket",
        "storage.ssi_evidence_prefix",
        "sweep.batch_size",
        "sweep.max_runtime_seconds",
        "vector.pgvector_dsn",
        "vector.vertex_ai_index",
        "vector.vertex_ai_serving_config",
    }
)

_MANIFEST_ALLOWLIST: frozenset[str] = frozenset(
    {
        "analytics.campaign_risk_weights",
        "analytics.infrastructure_clustering_interval_hours",
        "analytics.loss_linkage_confidence_threshold",
        "analytics.refresh_interval_minutes",
        "analytics.scheduled_report_check_interval_minutes",
        "analytics.scheduled_report_max_consecutive_failures",
        "analytics.watchlist_check_interval_minutes",
        "auto_investigate.domain_blocklist",
        "auto_investigate.enabled",
        "auto_investigate.max_concurrent",
        "auto_investigate.staleness_days",
        "db_admin.dev_password",
        "db_admin.dev_vault_password",
        "db_admin.prod_password",
        "db_admin.prod_vault_password",
        "email.from_address",
        "email.provider",
        "email.smtp_host",
        "email.smtp_password",
        "email.smtp_port",
        "email.smtp_user",
        "email.use_tls",
        "enrichment.blockchain_api_key",
        "enrichment.blockchain_vendor",
        "enrichment.securitytrails_api_key",
        "enrichment.takedown_check_interval_hours",
        "enrichment.takedown_max_urls_per_run",
        "feedback.enabled",
        "feedback.sheet_id",
        "partner_feed.default_page_size",
        "partner_feed.enabled",
        "partner_feed.max_page_size",
        "partner_feed.rate_limit_per_minute",
    }
)


def _collect_model_paths() -> set[str]:
    """Introspect the Pydantic Settings model and return all ``section.field`` paths.

    Top-level scalars (env, project_root, data_dir) are returned as-is.
    Nested section fields are returned as ``section.field``.
    Sub-nested sections (e.g., search.saved_search.field) are also handled.
    """
    # Import here so the script can report import errors clearly.
    from i4g.settings.config import Settings

    paths: set[str] = set()

    for name, field_info in Settings.model_fields.items():
        if name in _INTERNAL_FIELDS:
            continue

        annotation = field_info.annotation
        # Unwrap Optional / Union types to get the core type
        origin = get_origin(annotation)
        core_type = annotation
        if origin is not None:
            args = [a for a in annotation.__args__ if a is not type(None)]
            core_type = args[0] if args else annotation

        # Check if this is a nested BaseSettings / BaseModel section
        if isinstance(core_type, type) and hasattr(core_type, "model_fields"):
            _collect_section_fields(name, core_type, paths)
        else:
            paths.add(name)

    return paths


def _collect_section_fields(prefix: str, model_cls: Any, paths: set[str]) -> None:
    """Recursively collect ``prefix.field`` paths from a nested model."""
    for field_name, field_info in model_cls.model_fields.items():
        full_path = f"{prefix}.{field_name}"

        annotation = field_info.annotation
        origin = get_origin(annotation)
        core_type = annotation
        if origin is not None:
            args = [a for a in annotation.__args__ if a is not type(None)]
            core_type = args[0] if args else annotation

        if isinstance(core_type, type) and hasattr(core_type, "model_fields"):
            _collect_section_fields(full_path, core_type, paths)
        else:
            paths.add(full_path)


def _parse_toml_keys(toml_path: Path) -> set[str]:
    """Parse settings.default.toml and return all keys, including commented-out ones.

    Handles:
      - Active keys: ``key = value``
      - Commented keys: ``# key = value``
      - Section headers: ``[section]`` and ``[section.subsection]``
    """
    if not toml_path.exists():
        return set()

    keys: set[str] = set()
    current_section = ""

    for line in toml_path.read_text().splitlines():
        stripped = line.strip()

        # Section header (active or commented)
        section_match = re.match(r"^#?\s*\[([a-z_][a-z0-9_.]*)\]\s*$", stripped)
        if section_match:
            current_section = section_match.group(1)
            continue

        # Key = value (active)
        active_match = re.match(r"^([a-z_][a-z0-9_]*)\s*=", stripped)
        if active_match:
            key = active_match.group(1)
            path = f"{current_section}.{key}" if current_section else key
            keys.add(path)
            continue

        # Commented key = value
        comment_match = re.match(r"^#\s*([a-z_][a-z0-9_]*)\s*=", stripped)
        if comment_match:
            key = comment_match.group(1)
            path = f"{current_section}.{key}" if current_section else key
            keys.add(path)
            continue

    return keys


def _parse_manifest_paths(manifest_path: Path | None) -> set[str]:
    """Parse the settings manifest YAML and return all documented ``path`` values."""
    if manifest_path is None or not manifest_path.exists():
        return set()

    import yaml

    data = yaml.safe_load(manifest_path.read_text())
    if not data or "fields" not in data:
        return set()

    return {entry["path"] for entry in data["fields"] if "path" in entry}


def _find_manifest() -> Path | None:
    """Locate the settings manifest YAML."""
    for candidate in _MANIFEST_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


def _generate_toml_stub(missing_keys: set[str]) -> str:
    """Generate TOML stubs for missing keys, grouped by section."""
    sections: dict[str, list[str]] = {}
    for key in sorted(missing_keys):
        parts = key.split(".", 1)
        if len(parts) == 2:
            section, field = parts
        else:
            section, field = "", parts[0]
        sections.setdefault(section, []).append(field)

    lines: list[str] = []
    for section in sorted(sections):
        if section:
            lines.append(f"\n[{section}]")
        for field in sorted(sections[section]):
            lines.append(f"# {field} = ")
    return "\n".join(lines)


def main() -> int:
    """Run the drift check and return an exit code."""
    fix_mode = "--fix" in sys.argv
    strict_mode = "--strict" in sys.argv

    # 1. Collect model paths
    try:
        model_paths = _collect_model_paths()
    except ImportError as exc:
        print(f"ERROR: Cannot import settings model: {exc}", file=sys.stderr)
        print("  Ensure you are running from the core/ repo with the i4g package installed.", file=sys.stderr)
        return 1

    # 2. Parse TOML keys
    toml_keys = _parse_toml_keys(SETTINGS_TOML)

    # 3. Parse manifest paths
    manifest_path = _find_manifest()
    manifest_paths = _parse_manifest_paths(manifest_path)

    # 4. Compare (subtract known-drift allowlists unless --strict)
    toml_allow = frozenset() if strict_mode else _TOML_ALLOWLIST
    manifest_allow = frozenset() if strict_mode else _MANIFEST_ALLOWLIST
    missing_toml = model_paths - toml_keys - toml_allow
    missing_manifest = (model_paths - manifest_paths - manifest_allow) if manifest_paths else set()

    # Extra keys in TOML not in model (informational, not an error)
    extra_toml = toml_keys - model_paths

    has_errors = False

    if missing_toml:
        has_errors = True
        print(f"\n{'='*60}", file=sys.stderr)
        print("DRIFT: Pydantic fields missing from settings.default.toml", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)
        for key in sorted(missing_toml):
            print(f"  - {key}", file=sys.stderr)
        if fix_mode:
            print("\nSuggested TOML stubs to add:\n", file=sys.stderr)
            print(_generate_toml_stub(missing_toml), file=sys.stderr)

    if missing_manifest:
        has_errors = True
        print(f"\n{'='*60}", file=sys.stderr)
        print("DRIFT: Pydantic fields missing from settings_manifest.yaml", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)
        for key in sorted(missing_manifest):
            print(f"  - {key}", file=sys.stderr)
        if fix_mode:
            print(
                "\nRun: conda run -n i4g i4g settings export-manifest --docs-repo ../docs",
                file=sys.stderr,
            )

    if extra_toml:
        print(f"\n{'='*60}", file=sys.stderr)
        print("INFO: Keys in settings.default.toml not in Pydantic model (may be stale)", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)
        for key in sorted(extra_toml):
            print(f"  - {key}", file=sys.stderr)

    if not has_errors and not extra_toml:
        msg = "OK: Settings model, default.toml, and manifest are in sync."
        if not strict_mode and (len(_TOML_ALLOWLIST) + len(_MANIFEST_ALLOWLIST)) > 0:
            msg += f" ({len(_TOML_ALLOWLIST)} TOML + {len(_MANIFEST_ALLOWLIST)} manifest entries allowlisted)"
        print(msg)

    if not has_errors and extra_toml:
        msg = "OK: No missing keys (some extra TOML keys noted above — informational only)."
        if not strict_mode and (len(_TOML_ALLOWLIST) + len(_MANIFEST_ALLOWLIST)) > 0:
            msg += f" ({len(_TOML_ALLOWLIST)} TOML + {len(_MANIFEST_ALLOWLIST)} manifest entries allowlisted)"
        print(msg)

    return 1 if has_errors else 0


if __name__ == "__main__":
    sys.exit(main())
