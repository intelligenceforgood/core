"""Test bundle management for entity extraction QA.

A *bundle* is a directory containing a ``manifest.json``, ``cases/*.json`` files
with input text, and ``labels/*.json`` files with golden expected entities.

Bundles live locally under ``data/entity-qa/bundles/<name>/`` and can be
downloaded from GCS at ``gs://i4g-dev-data-bundles/entity-qa/<name>/``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BundleCase:
    """A single test case: text to extract entities from."""

    id: str
    category: str
    text: str


@dataclass(frozen=True, slots=True)
class BundleLabel:
    """Golden labels for a single test case."""

    id: str
    expected: dict[str, list[str]]
    """Mapping of entity_type → list of expected canonical values."""


@dataclass(slots=True)
class Bundle:
    """A loaded test bundle with cases and optional labels."""

    name: str
    description: str
    created: str
    cases: list[BundleCase] = field(default_factory=list)
    labels: dict[str, BundleLabel] = field(default_factory=dict)
    """Labels keyed by case ID."""

    @property
    def has_labels(self) -> bool:
        """Whether this bundle has golden labels."""
        return len(self.labels) > 0

    @property
    def labeled_count(self) -> int:
        """Number of cases with golden labels."""
        return sum(1 for c in self.cases if c.id in self.labels)


def default_bundles_dir() -> Path:
    """Return the default local bundles directory."""
    from i4g.settings import get_settings

    settings = get_settings()
    return Path(settings.project_root) / "data" / "entity-qa" / "bundles"


def list_bundles(bundles_dir: Path | None = None) -> list[dict[str, str | int]]:
    """List locally available bundles.

    Returns:
        List of dicts with ``name``, ``description``, ``created``,
        ``case_count``, ``label_count``.
    """
    root = bundles_dir or default_bundles_dir()
    if not root.exists():
        return []

    results = []
    for path in sorted(root.iterdir()):
        manifest_path = path / "manifest.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text())
        case_dir = path / "cases"
        label_dir = path / "labels"
        case_count = len(list(case_dir.glob("*.json"))) if case_dir.exists() else 0
        label_count = len(list(label_dir.glob("*.json"))) if label_dir.exists() else 0
        results.append(
            {
                "name": manifest.get("name", path.name),
                "description": manifest.get("description", ""),
                "created": manifest.get("created", "unknown"),
                "case_count": case_count,
                "label_count": label_count,
            }
        )
    return results


def load_bundle(name: str, bundles_dir: Path | None = None) -> Bundle:
    """Load a bundle from disk by name.

    Args:
        name: Bundle directory name.
        bundles_dir: Override bundles root directory.

    Returns:
        A populated ``Bundle`` instance.

    Raises:
        FileNotFoundError: If the bundle directory or manifest doesn't exist.
    """
    root = bundles_dir or default_bundles_dir()
    bundle_path = root / name
    manifest_path = bundle_path / "manifest.json"

    if not manifest_path.exists():
        raise FileNotFoundError(f"Bundle not found: {bundle_path}")

    manifest = json.loads(manifest_path.read_text())

    bundle = Bundle(
        name=manifest.get("name", name),
        description=manifest.get("description", ""),
        created=manifest.get("created", "unknown"),
    )

    # Load cases.
    case_dir = bundle_path / "cases"
    if case_dir.exists():
        for case_file in sorted(case_dir.glob("*.json")):
            data = json.loads(case_file.read_text())
            bundle.cases.append(
                BundleCase(
                    id=data["id"],
                    category=data.get("category", "unknown"),
                    text=data["text"],
                )
            )

    # Load labels.
    label_dir = bundle_path / "labels"
    if label_dir.exists():
        for label_file in sorted(label_dir.glob("*.json")):
            data = json.loads(label_file.read_text())
            bundle.labels[data["id"]] = BundleLabel(
                id=data["id"],
                expected=data.get("expected", {}),
            )

    return bundle


def save_bundle(bundle: Bundle, bundles_dir: Path | None = None) -> Path:
    """Save a bundle to disk.

    Args:
        bundle: The bundle to save.
        bundles_dir: Override bundles root directory.

    Returns:
        Path to the bundle directory.
    """
    root = bundles_dir or default_bundles_dir()
    bundle_path = root / bundle.name
    bundle_path.mkdir(parents=True, exist_ok=True)
    case_dir = bundle_path / "cases"
    case_dir.mkdir(exist_ok=True)
    label_dir = bundle_path / "labels"
    label_dir.mkdir(exist_ok=True)

    # Write manifest.
    manifest = {
        "name": bundle.name,
        "description": bundle.description,
        "created": bundle.created,
        "cases": [{"id": c.id, "filename": f"{c.id}.json"} for c in bundle.cases],
    }
    (bundle_path / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    # Write cases.
    for case in bundle.cases:
        data = {"id": case.id, "category": case.category, "text": case.text}
        (case_dir / f"{case.id}.json").write_text(json.dumps(data, indent=2) + "\n")

    # Write labels.
    for label in bundle.labels.values():
        data = {"id": label.id, "expected": label.expected}
        (label_dir / f"{label.id}.json").write_text(json.dumps(data, indent=2) + "\n")

    return bundle_path


def create_bundle_from_golden_set(
    golden_path: Path,
    bundle_name: str,
    description: str = "",
    bundles_dir: Path | None = None,
) -> Bundle:
    """Create a bundle from the golden test set JSON file.

    Args:
        golden_path: Path to the golden test set JSON file.
        bundle_name: Name for the new bundle.
        description: Optional description.
        bundles_dir: Override bundles root directory.

    Returns:
        The created ``Bundle``.
    """
    data = json.loads(golden_path.read_text())

    bundle = Bundle(
        name=bundle_name,
        description=description or f"Bundle created from {golden_path.name}",
        created=datetime.now(tz=UTC).isoformat(),
    )

    for entry in data:
        bundle.cases.append(
            BundleCase(
                id=entry["id"],
                category=entry.get("category", "unknown"),
                text=entry["text"],
            )
        )
        if "expected" in entry:
            bundle.labels[entry["id"]] = BundleLabel(
                id=entry["id"],
                expected=entry["expected"],
            )

    save_bundle(bundle, bundles_dir=bundles_dir)
    return bundle


def create_bundle_from_files(
    input_dir: Path,
    bundle_name: str,
    description: str = "",
    bundles_dir: Path | None = None,
) -> Bundle:
    """Create a bundle from raw text files in a directory.

    Each ``.txt`` file becomes a case. No labels are created.

    Args:
        input_dir: Directory containing ``.txt`` files.
        bundle_name: Name for the new bundle.
        description: Optional description.
        bundles_dir: Override bundles root directory.

    Returns:
        The created ``Bundle``.
    """
    bundle = Bundle(
        name=bundle_name,
        description=description or f"Bundle created from {input_dir}",
        created=datetime.now(tz=UTC).isoformat(),
    )

    for txt_file in sorted(input_dir.glob("*.txt")):
        case_id = txt_file.stem
        bundle.cases.append(
            BundleCase(
                id=case_id,
                category="unknown",
                text=txt_file.read_text().strip(),
            )
        )

    save_bundle(bundle, bundles_dir=bundles_dir)
    return bundle


def download_bundle(
    name: str,
    bucket_prefix: str = "gs://i4g-dev-data-bundles/entity-qa",
    bundles_dir: Path | None = None,
) -> Path:
    """Download a bundle from GCS.

    Args:
        name: Bundle name (directory in GCS).
        bucket_prefix: GCS prefix.
        bundles_dir: Override bundles root directory.

    Returns:
        Path to the downloaded bundle directory.

    Raises:
        RuntimeError: If ``gsutil`` is not available or download fails.
    """
    import subprocess

    root = bundles_dir or default_bundles_dir()
    bundle_path = root / name
    bundle_path.mkdir(parents=True, exist_ok=True)

    src = f"{bucket_prefix}/{name}/"
    try:
        subprocess.run(
            ["gsutil", "-m", "rsync", "-r", src, str(bundle_path)],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as err:
        raise RuntimeError("gsutil not found — install the Google Cloud SDK") from err
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Failed to download bundle {name}: {exc.stderr}") from exc

    return bundle_path


def add_case_to_bundle(
    bundle_name: str,
    text: str,
    *,
    expected: dict[str, list[str]] | None = None,
    case_id: str | None = None,
    category: str = "manual",
    bundles_dir: Path | None = None,
) -> BundleCase:
    """Add a single case (and optional label) to an existing bundle.

    Args:
        bundle_name: Name of the target bundle.
        text: Case text to add.
        expected: Optional golden label ``{entity_type: [values]}``.
        case_id: Custom case ID. Auto-generated if omitted.
        category: Case category tag.
        bundles_dir: Override bundles root directory.

    Returns:
        The newly created ``BundleCase``.

    Raises:
        FileNotFoundError: If the bundle doesn't exist.
    """
    import uuid

    bundle = load_bundle(bundle_name, bundles_dir=bundles_dir)

    cid = case_id or f"manual-{uuid.uuid4().hex[:8]}"
    case = BundleCase(id=cid, category=category, text=text)
    bundle.cases.append(case)

    if expected:
        bundle.labels[cid] = BundleLabel(id=cid, expected=expected)

    save_bundle(bundle, bundles_dir=bundles_dir)
    return case
