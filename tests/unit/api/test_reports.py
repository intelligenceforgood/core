"""Tests for the dossier reports API."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from i4g.api.app import create_app
from i4g.reports.bundle_builder import DossierCandidate, DossierPlan
from i4g.store.dossier_queue_store import DossierQueueStore


def _sample_plan(plan_id: str = "test-plan-001") -> DossierPlan:
    candidate = DossierCandidate(
        case_id="case-1",
        loss_amount_usd=Decimal("125000"),
        accepted_at=datetime(2025, 12, 1, tzinfo=timezone.utc),
        jurisdiction="US-CA",
        cross_border=True,
        primary_entities=("wallet:test",),
    )
    return DossierPlan(
        plan_id=plan_id,
        jurisdiction_key="US-CA",
        created_at=datetime(2025, 12, 2, tzinfo=timezone.utc),
        total_loss_usd=Decimal("125000"),
        cases=[candidate],
        bundle_reason="unit-test",
        cross_border=True,
        shared_drive_parent_id="drive-folder",
    )


@pytest.fixture()
def queue_store(tmp_path) -> DossierQueueStore:
    return DossierQueueStore(db_path=tmp_path / "dossier_queue.db")


def test_list_dossiers_returns_manifest_and_signature(tmp_path, queue_store, monkeypatch) -> None:
    from i4g.api import reports as reports_api

    plan = _sample_plan()
    queue_store.enqueue_plan(plan)
    queue_store.mark_complete(plan.plan_id, warnings=["pilot-warning"])

    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = artifact_dir / f"{plan.plan_id}.json"
    signature_path = artifact_dir / f"{plan.plan_id}.signatures.json"

    manifest_payload = {
        "plan_id": plan.plan_id,
        "signature_manifest": {"path": str(signature_path), "algorithm": "sha256"},
        "assets": {"timeline_chart": "chart.png"},
        "exports": {"pdf_path": "test-plan-001.pdf", "html_path": "test-plan-001.html"},
        "template_render": {"path": "test-plan-001.md"},
    }
    manifest_path.write_text(json.dumps(manifest_payload))
    signature_payload = {
        "algorithm": "sha256",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": [{"label": "manifest", "path": str(manifest_path), "size_bytes": 128, "hash": "abc"}],
        "warnings": [],
    }
    signature_path.write_text(json.dumps(signature_payload))

    monkeypatch.setattr(reports_api, "build_dossier_queue_store", lambda: queue_store)
    monkeypatch.setattr(reports_api, "ARTIFACTS_DIR", artifact_dir)

    client = TestClient(create_app())
    response = client.get("/reports/dossiers", params={"status": "completed", "include_manifest": True})

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    record = body["items"][0]
    assert record["plan_id"] == plan.plan_id
    assert record["manifest"]["plan_id"] == plan.plan_id
    assert record["signature_manifest"]["algorithm"] == "sha256"
    assert record["signature_manifest"]["artifacts"][0]["label"] == "manifest"
    assert record["artifact_warnings"] == []
    downloads = record["downloads"]
    assert downloads["local"]["manifest"].endswith(f"{plan.plan_id}.json")
    assert downloads["local"]["signature_manifest"].endswith(f"{plan.plan_id}.signatures.json")
    assert downloads["local"]["pdf"].endswith("test-plan-001.pdf")
    assert downloads["local"]["html"].endswith("test-plan-001.html")
    assert downloads["local"]["markdown"].endswith("test-plan-001.md")
    assert downloads["api"]["manifest"].endswith("/download/manifest")
    assert downloads["api"]["signature"].endswith("/download/signature")
    assert downloads["remote"] == []


def test_list_dossiers_handles_missing_manifest(tmp_path, queue_store, monkeypatch) -> None:
    from i4g.api import reports as reports_api

    plan = _sample_plan(plan_id="plan-missing-manifest")
    queue_store.enqueue_plan(plan)
    queue_store.mark_complete(plan.plan_id, warnings=[])

    monkeypatch.setattr(reports_api, "build_dossier_queue_store", lambda: queue_store)
    monkeypatch.setattr(reports_api, "ARTIFACTS_DIR", tmp_path / "missing")

    client = TestClient(create_app())
    response = client.get("/reports/dossiers", params={"status": "completed"})

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    record = body["items"][0]
    assert record["manifest"] is None
    assert record["signature_manifest"] is None
    assert any("Manifest missing" in warning for warning in record["artifact_warnings"])
    downloads = record["downloads"]
    assert downloads["local"]["manifest"] is None
    assert downloads["local"]["signature_manifest"] is None
    assert downloads["remote"] == []


def test_fetch_signature_manifest(tmp_path, queue_store, monkeypatch) -> None:
    from i4g.api import reports as reports_api

    plan = _sample_plan(plan_id="plan-sig")
    queue_store.enqueue_plan(plan)
    queue_store.mark_complete(plan.plan_id, warnings=[])

    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = artifact_dir / f"{plan.plan_id}.json"
    signature_path = artifact_dir / f"{plan.plan_id}.signatures.json"
    manifest_payload = {"plan_id": plan.plan_id, "signature_manifest": {"path": str(signature_path)}}
    manifest_path.write_text(json.dumps(manifest_payload))
    signature_payload = {"algorithm": "sha256", "artifacts": []}
    signature_path.write_text(json.dumps(signature_payload))

    monkeypatch.setattr(reports_api, "build_dossier_queue_store", lambda: queue_store)
    monkeypatch.setattr(reports_api, "ARTIFACTS_DIR", artifact_dir)

    client = TestClient(create_app())
    response = client.get(f"/reports/dossiers/{plan.plan_id}/signature_manifest")
    assert response.status_code == 200
    assert response.json()["algorithm"] == "sha256"


def test_download_artifact_returns_file(tmp_path, queue_store, monkeypatch) -> None:
    from i4g.api import reports as reports_api

    plan = _sample_plan(plan_id="plan-dl")
    queue_store.enqueue_plan(plan)
    queue_store.mark_complete(plan.plan_id, warnings=[])

    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = artifact_dir / f"{plan.plan_id}.json"
    pdf_path = artifact_dir / f"{plan.plan_id}.pdf"
    pdf_path.write_text("pdf-bytes")
    manifest_payload = {
        "plan_id": plan.plan_id,
        "signature_manifest": {"path": str(artifact_dir / f"{plan.plan_id}.signatures.json")},
        "exports": {"pdf_path": str(pdf_path)},
    }
    manifest_path.write_text(json.dumps(manifest_payload))
    signature_path = artifact_dir / f"{plan.plan_id}.signatures.json"
    signature_path.write_text(json.dumps({"algorithm": "sha256", "artifacts": []}))

    monkeypatch.setattr(reports_api, "build_dossier_queue_store", lambda: queue_store)
    monkeypatch.setattr(reports_api, "ARTIFACTS_DIR", artifact_dir)

    client = TestClient(create_app())
    response = client.get(f"/reports/dossiers/{plan.plan_id}/download/pdf")
    assert response.status_code == 200
    assert response.content == b"pdf-bytes"


def test_drive_acl_endpoint_returns_acl(tmp_path, queue_store, monkeypatch) -> None:
    from i4g.api import reports as reports_api

    plan = _sample_plan(plan_id="plan-drive-acl")
    queue_store.enqueue_plan(plan)
    queue_store.mark_complete(plan.plan_id, warnings=[])

    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = artifact_dir / f"{plan.plan_id}.json"
    manifest_payload = {
        "plan_id": plan.plan_id,
        "shared_drive_parent_id": "drive-folder",
        "signature_manifest": {"path": str(artifact_dir / f"{plan.plan_id}.signatures.json")},
    }
    manifest_path.write_text(json.dumps(manifest_payload))
    signature_path = artifact_dir / f"{plan.plan_id}.signatures.json"
    signature_path.write_text(json.dumps({"algorithm": "sha256", "artifacts": []}))

    monkeypatch.setattr(reports_api, "build_dossier_queue_store", lambda: queue_store)
    monkeypatch.setattr(reports_api, "ARTIFACTS_DIR", artifact_dir)

    class _StubUploader:
        def __init__(self, drive_parent_id: str | None = None) -> None:
            self.drive_parent_id = drive_parent_id

        def fetch_acl(self, folder_id: str | None = None):  # type: ignore[override]
            assert folder_id == "drive-folder"
            return (
                {
                    "folder_id": "drive-folder",
                    "name": "LEA Shared",
                    "link": "https://drive.google.com/drive/folders/drive-folder",
                    "drive_id": "drive-1",
                    "permissions": [{"id": "perm-1", "type": "group", "role": "reader", "principal": "analysts"}],
                },
                ["cached"],
            )

    monkeypatch.setattr(reports_api, "DossierUploader", _StubUploader)

    client = TestClient(create_app())
    response = client.get(f"/reports/dossiers/{plan.plan_id}/drive_acl")

    assert response.status_code == 200
    body = response.json()
    assert body["folder_id"] == "drive-folder"
    assert body["folder_name"] == "LEA Shared"
    assert body["permissions"][0]["role"] == "reader"
    assert body["warnings"] == ["cached"]


def test_drive_acl_missing_folder_id_returns_404(tmp_path, queue_store, monkeypatch) -> None:
    from i4g.api import reports as reports_api

    plan = _sample_plan(plan_id="plan-drive-missing")
    queue_store.enqueue_plan(plan)
    queue_store.mark_complete(plan.plan_id, warnings=[])

    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = artifact_dir / f"{plan.plan_id}.json"
    manifest_path.write_text(json.dumps({"plan_id": plan.plan_id}))

    monkeypatch.setattr(reports_api, "build_dossier_queue_store", lambda: queue_store)
    monkeypatch.setattr(reports_api, "ARTIFACTS_DIR", artifact_dir)

    client = TestClient(create_app())
    response = client.get(f"/reports/dossiers/{plan.plan_id}/drive_acl")

    assert response.status_code == 404
