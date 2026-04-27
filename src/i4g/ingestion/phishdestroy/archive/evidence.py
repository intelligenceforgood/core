"""Evidence-blob persistence for the PhishDestroy archive adapters (Sprint 2 §2.4 / Phase C).

Helpers that route chat exports, photos, panel captures, and source maps through the
project-standard ``storage/evidence.py`` backend, returning SHA-256 pointers the calling
adapter stamps onto its database rows.

References:
    - PRD §3 ("Immutable evidence") and §5.2 (`evidence_blob_sha256` column on
      `chat_sessions`) — `planning/prd_phishdestroy_integration.md`.
    - Sprint 2 §2.4 — `planning/tasks/phishdestroy_integration_tasks.md`.
    - Phase C manifest — `planning/handoffs/2026-04-27-phishdestroy-sprint-2-phaseC.manifest.md`.
"""

from __future__ import annotations

import logging
import mimetypes
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from i4g.storage.evidence import EvidenceStorage

LOGGER = logging.getLogger("i4g.ingestion.phishdestroy.archive.evidence")


class BlobKind(StrEnum):
    """Categorisation of evidence blobs persisted alongside an archive ingest."""

    CHAT_EXPORT = "chat_export"
    PHOTO = "photo"
    PANEL_CAPTURE = "panel_capture"
    SOURCE_MAP = "source_map"


# TWP-specific Phase C defaults. Phase D will generalise these into a per-team
# registry (or settings list) so additional teams can register their own file
# categorisation without editing this module.
_PHOTO_SUFFIXES: frozenset[str] = frozenset({".png", ".jpg", ".jpeg"})
_SOURCE_MAP_SUFFIXES: frozenset[str] = frozenset({".map"})
_PANEL_CAPTURE_NAMES: tuple[str, ...] = (
    "chats.html",
    "wallets_full.html",
    "analytics.html",
    "index.html",
)
_CHAT_EXPORT_FILENAME = "chats_translated.json"


@dataclass(frozen=True)
class EvidenceBlobRef:
    """Reference to a single evidence blob persisted via :class:`EvidenceStorage`."""

    kind: BlobKind
    file_name: str
    sha256: str
    size_bytes: int
    storage_uri: str
    content_type: str | None

    def to_metadata_dict(self) -> dict[str, object]:
        """Return the literal shape stored under ``infrastructure_profiles.metadata_json``.

        Key order matches the Phase C manifest §"Behaviour contract — photo / panel-capture /
        source-map blobs" §3 spec exactly: ``kind, file_name, sha256, size_bytes, storage_uri,
        content_type``. ``kind`` is serialised as the StrEnum value string.
        """
        return {
            "kind": self.kind.value,
            "file_name": self.file_name,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "storage_uri": self.storage_uri,
            "content_type": self.content_type,
        }


def predict_storage_uri(evidence_storage: EvidenceStorage, intake_id: str, file_name: str) -> str:
    """Predict the URI :meth:`EvidenceStorage.save` would assign without writing.

    Used to consult :meth:`EvidenceStorage.exists` before calling :meth:`save`, so
    re-ingestion of the same upstream commit does not redundantly rewrite blobs.

    Note:
        Reads private attributes (``_backend``, ``_local_dir``, ``_bucket_name``) on
        ``EvidenceStorage``. These are treated as a known internal API for this sibling
        helper. Phase D will revisit if ``EvidenceStorage`` grows a public predictor.
    """
    backend = getattr(evidence_storage, "_backend", "local")
    if backend == "gcs":
        bucket = evidence_storage._bucket_name
        return f"gs://{bucket}/intake/{intake_id}/{file_name}"
    local_dir = evidence_storage._local_dir
    assert local_dir is not None  # local backend always has _local_dir set
    return str(Path(local_dir) / intake_id / file_name)


def _guess_content_type(file_name: str) -> str | None:
    """Return a best-effort MIME type for *file_name*, or ``None`` if unknown."""
    content_type, _ = mimetypes.guess_type(file_name)
    if content_type is not None:
        return content_type
    # Source maps are commonly served as JSON.
    if file_name.lower().endswith(".map"):
        return "application/json"
    return None


def _persist_or_reuse(
    evidence_storage: EvidenceStorage,
    intake_id: str,
    file_name: str,
    data: bytes,
    content_type: str | None,
) -> tuple[str, str, int]:
    """Persist *data* via the storage backend, reusing a matching pre-existing blob.

    Returns:
        Tuple of ``(sha256, storage_uri, size_bytes)``.
    """
    expected_sha = EvidenceStorage.compute_sha256(data)
    predicted_uri = predict_storage_uri(evidence_storage, intake_id, file_name)

    if evidence_storage.exists(predicted_uri):
        retrieved = evidence_storage.retrieve(predicted_uri)
        if retrieved is not None and retrieved.checksum_sha256 == expected_sha:
            return expected_sha, predicted_uri, retrieved.size_bytes
        LOGGER.warning(
            "Evidence blob at %s exists but SHA differs (expected=%s, found=%s); overwriting.",
            predicted_uri,
            expected_sha,
            retrieved.checksum_sha256 if retrieved is not None else "<missing>",
        )

    attachment = evidence_storage.save(
        intake_id=intake_id,
        file_name=file_name,
        data=data,
        content_type=content_type,
    )
    return attachment.checksum_sha256, attachment.storage_uri, attachment.size_bytes


def persist_chat_export(
    evidence_storage: EvidenceStorage | None,
    team: str,
    file_path: Path,
) -> tuple[str, str] | None:
    """Persist the team's ``chats_translated.json`` as a single evidence blob.

    Args:
        evidence_storage: Configured evidence backend, or ``None`` to disable
            persistence (Phase B compatibility path — caller must leave
            ``evidence_blob_sha256`` NULL).
        team: Team directory name, e.g. ``"TrustWalletPanel"``.
        file_path: Absolute path to the chat-export JSON file.

    Returns:
        ``(sha256, storage_uri)`` for the persisted (or pre-existing-and-matching) blob,
        or ``None`` when *evidence_storage* is ``None``.
    """
    if evidence_storage is None:
        return None

    data = file_path.read_bytes()
    intake_id = f"phishdestroy-archive/{team}"
    sha, uri, _ = _persist_or_reuse(
        evidence_storage,
        intake_id=intake_id,
        file_name=file_path.name,
        data=data,
        content_type="application/json",
    )
    return sha, uri


def _classify(file_path: Path) -> BlobKind | None:
    """Categorise *file_path* under one of the recognised PhaseC blob kinds, or ``None``."""
    if file_path.name == _CHAT_EXPORT_FILENAME:
        # Handled separately by ``persist_chat_export``.
        return None
    suffix = file_path.suffix.lower()
    if suffix in _PHOTO_SUFFIXES:
        return BlobKind.PHOTO
    if file_path.name in _PANEL_CAPTURE_NAMES:
        return BlobKind.PANEL_CAPTURE
    if suffix in _SOURCE_MAP_SUFFIXES:
        return BlobKind.SOURCE_MAP
    return None


def persist_team_blobs(
    evidence_storage: EvidenceStorage | None,
    team: str,
    team_dir: Path,
) -> list[EvidenceBlobRef]:
    """Persist photo / panel-capture / source-map blobs for *team*.

    Walks *team_dir* non-recursively, deduplicates by exact filename, and persists each
    matching file via :class:`EvidenceStorage`. Skips ``chats_translated.json`` (handled
    by :func:`persist_chat_export`).

    Args:
        evidence_storage: Configured evidence backend, or ``None`` to disable
            persistence (returns ``[]`` for Phase B compatibility).
        team: Team directory name.
        team_dir: Absolute path to the team directory.

    Returns:
        List of :class:`EvidenceBlobRef` sorted deterministically by ``(kind, file_name)``.
    """
    if evidence_storage is None:
        return []

    intake_id = f"phishdestroy-archive/{team}"
    seen_names: set[str] = set()
    refs: list[EvidenceBlobRef] = []

    for entry in sorted(team_dir.iterdir(), key=lambda p: p.name):
        if not entry.is_file():
            continue
        if entry.name in seen_names:
            continue
        kind = _classify(entry)
        if kind is None:
            continue
        seen_names.add(entry.name)

        data = entry.read_bytes()
        content_type = _guess_content_type(entry.name)
        sha, uri, size_bytes = _persist_or_reuse(
            evidence_storage,
            intake_id=intake_id,
            file_name=entry.name,
            data=data,
            content_type=content_type,
        )
        refs.append(
            EvidenceBlobRef(
                kind=kind,
                file_name=entry.name,
                sha256=sha,
                size_bytes=size_bytes,
                storage_uri=uri,
                content_type=content_type,
            )
        )

    refs.sort(key=lambda ref: (ref.kind.value, ref.file_name))
    return refs


__all__ = [
    "BlobKind",
    "EvidenceBlobRef",
    "persist_chat_export",
    "persist_team_blobs",
    "predict_storage_uri",
]
