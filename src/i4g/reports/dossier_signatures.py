"""Helpers that compute and verify dossier artifact signature manifests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True)
class ArtifactSignature:
    """Hash + size metadata for a single artifact."""

    label: str
    path: Path
    size_bytes: int
    hash_value: str

    def to_dict(self) -> dict:
        """Return a JSON-serializable dictionary."""

        return {
            "label": self.label,
            "path": str(self.path),
            "size_bytes": self.size_bytes,
            "hash": self.hash_value,
        }


@dataclass(frozen=True)
class SignatureManifest:
    """Structured payload that captures dossier artifact signatures."""

    algorithm: str
    generated_at: datetime
    artifacts: Sequence[ArtifactSignature]
    uploads: Sequence["UploadedArtifactSignature"] = field(default_factory=tuple)
    warnings: Sequence[str] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        """Return a JSON-serializable manifest."""

        return {
            "algorithm": self.algorithm,
            "generated_at": self.generated_at.isoformat(),
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "uploads": [upload.to_dict() for upload in self.uploads],
            "warnings": list(self.warnings),
        }

    def with_uploads(
        self,
        uploads: Sequence["UploadedArtifactSignature"],
        *,
        warnings: Sequence[str] | None = None,
    ) -> "SignatureManifest":
        merged_warnings = list(self.warnings)
        if warnings:
            merged_warnings.extend(warnings)
        return SignatureManifest(
            algorithm=self.algorithm,
            generated_at=self.generated_at,
            artifacts=self.artifacts,
            uploads=tuple(uploads),
            warnings=tuple(merged_warnings),
        )


@dataclass(frozen=True)
class UploadedArtifactSignature:
    """Hash metadata for artifacts after they are uploaded to remote storage."""

    label: str
    remote_ref: str
    hash_value: str
    algorithm: str
    size_bytes: int | None = None

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "remote_ref": self.remote_ref,
            "hash": self.hash_value,
            "algorithm": self.algorithm,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True)
class ArtifactVerification:
    """Result describing whether an artifact hash/path could be validated."""

    label: str
    path: Path | None
    expected_hash: str | None
    actual_hash: str | None
    exists: bool
    matches: bool
    size_bytes: int | None = None
    error: str | None = None


@dataclass(frozen=True)
class ManifestVerificationReport:
    """Aggregated verification result for a signature manifest."""

    algorithm: str
    artifacts: Sequence[ArtifactVerification]
    warnings: Sequence[str] = field(default_factory=tuple)

    @property
    def missing_count(self) -> int:
        return sum(1 for artifact in self.artifacts if not artifact.exists)

    @property
    def mismatch_count(self) -> int:
        return sum(1 for artifact in self.artifacts if artifact.exists and not artifact.matches)

    @property
    def all_verified(self) -> bool:
        return self.missing_count == 0 and self.mismatch_count == 0


def generate_signature_manifest(
    entries: Iterable[tuple[str, Path | None]],
    *,
    algorithm: str = "sha256",
    generated_at: datetime | None = None,
    relative_to: Path | None = None,
) -> SignatureManifest:
    """Compute the signature manifest for the provided artifact entries."""

    artifacts: list[ArtifactSignature] = []
    warnings: list[str] = []

    for label, path in entries:
        if not path:
            warnings.append(f"Artifact {label} missing path; skipping signature")
            continue
        resolved = Path(path)
        if not resolved.exists():
            warnings.append(f"Artifact {label} missing on disk at {resolved}")
            continue
        hash_value = _hash_file(resolved, algorithm=algorithm)
        size_bytes = resolved.stat().st_size
        manifest_path = resolved
        if relative_to is not None:
            base_path = Path(relative_to).resolve()
            try:
                manifest_path = resolved.resolve().relative_to(base_path)
            except ValueError:
                manifest_path = resolved
        artifacts.append(
            ArtifactSignature(label=label, path=manifest_path, size_bytes=size_bytes, hash_value=hash_value)
        )

    timestamp = generated_at or datetime.now(timezone.utc)
    return SignatureManifest(
        algorithm=algorithm,
        generated_at=timestamp,
        artifacts=tuple(artifacts),
        uploads=tuple(),
        warnings=tuple(warnings),
    )


def build_uploaded_signatures(
    uploads: Iterable[Mapping[str, object]] | None,
    *,
    default_algorithm: str,
) -> tuple[Sequence[UploadedArtifactSignature], Sequence[str]]:
    """Convert raw upload metadata into UploadedArtifactSignature objects."""

    results: list[UploadedArtifactSignature] = []
    warnings: list[str] = []
    if not uploads:
        return tuple(), tuple()
    for row in uploads:
        if not isinstance(row, Mapping):
            warnings.append("Encountered non-mapping upload entry; skipping")
            continue
        label = str(row.get("label") or "upload")
        remote_ref = str(row.get("remote_ref") or row.get("id") or "")
        hash_value = str(row.get("hash") or "")
        algorithm = str(row.get("algorithm") or default_algorithm)
        size_bytes = row.get("size_bytes")
        if not remote_ref or not hash_value:
            warnings.append(f"Upload {label} missing remote_ref or hash; skipping")
            continue
        if algorithm != default_algorithm:
            warnings.append(
                f"Upload {label} hash algorithm {algorithm} differs from manifest algorithm {default_algorithm}"
            )
        results.append(
            UploadedArtifactSignature(
                label=label,
                remote_ref=remote_ref,
                hash_value=hash_value,
                algorithm=algorithm,
                size_bytes=int(size_bytes) if size_bytes is not None else None,
            )
        )
    return tuple(results), tuple(warnings)


def verify_manifest_payload(
    manifest: Mapping[str, object],
    *,
    base_path: Path | None = None,
    algorithm: str | None = None,
) -> ManifestVerificationReport:
    """Verify the artifacts referenced inside a manifest payload."""

    manifest_algorithm = str(manifest.get("algorithm") or algorithm or "sha256")
    manifest_warnings = list(manifest.get("warnings") or [])
    artifact_rows = manifest.get("artifacts") or []
    if not isinstance(artifact_rows, Iterable):
        raise ValueError("Manifest artifacts field must be iterable")

    results: list[ArtifactVerification] = []
    for raw_artifact in artifact_rows:
        if not isinstance(raw_artifact, Mapping):
            manifest_warnings.append("Encountered non-dict artifact entry; skipping")
            continue
        label = str(raw_artifact.get("label") or "artifact")
        raw_path = raw_artifact.get("path")
        expected_hash = raw_artifact.get("hash")
        resolved_path: Path | None = None
        exists = False
        actual_hash: str | None = None
        size_bytes: int | None = None
        error: str | None = None

        if isinstance(raw_path, str):
            candidate = Path(raw_path)
            if candidate.is_absolute():
                resolved_path = candidate
            elif candidate.exists():
                # Avoid double-prefixing base_path when the manifest already stores a rooted path.
                resolved_path = candidate.resolve()
            elif base_path:
                resolved_path = (Path(base_path) / candidate).resolve()
            else:
                resolved_path = candidate
        elif isinstance(raw_path, Path):
            resolved_path = raw_path

        if resolved_path and resolved_path.exists():
            exists = True
            size_bytes = resolved_path.stat().st_size
            try:
                actual_hash = _hash_file(resolved_path, algorithm=manifest_algorithm)
            except ValueError as exc:
                error = str(exc)
            except OSError as exc:
                error = f"Failed to read {resolved_path}: {exc}"
        else:
            exists = False

        if expected_hash is None:
            manifest_warnings.append(f"Artifact {label} missing expected hash value")

        matches = bool(exists and actual_hash and expected_hash and actual_hash == expected_hash)

        results.append(
            ArtifactVerification(
                label=label,
                path=resolved_path,
                expected_hash=str(expected_hash) if expected_hash is not None else None,
                actual_hash=actual_hash,
                exists=exists,
                matches=matches,
                size_bytes=size_bytes,
                error=error,
            )
        )

    return ManifestVerificationReport(
        algorithm=manifest_algorithm,
        artifacts=tuple(results),
        warnings=tuple(manifest_warnings),
    )


def verify_manifest_file(manifest_path: Path | str) -> ManifestVerificationReport:
    """Load and verify the manifest data stored at ``manifest_path``."""

    resolved = Path(manifest_path)
    payload = json.loads(resolved.read_text())
    return verify_manifest_payload(payload, base_path=resolved.parent)


def _hash_file(path: Path, *, algorithm: str) -> str:
    try:
        digest = hashlib.new(algorithm)
    except ValueError as exc:  # pragma: no cover - invalid algorithm handled by caller
        raise ValueError(f"Unsupported hash algorithm: {algorithm}") from exc
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "ArtifactSignature",
    "ArtifactVerification",
    "ManifestVerificationReport",
    "SignatureManifest",
    "generate_signature_manifest",
    "verify_manifest_payload",
    "verify_manifest_file",
]
