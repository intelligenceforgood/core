import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from i4g.reports.bundle_builder import DossierCandidate, DossierPlan
from i4g.reports.dossier_exports import DossierExporter
from i4g.reports.dossier_pipeline import DossierGenerator
from i4g.reports.dossier_uploads import DossierUploader


def test_exporter_generates_pdf_and_html(tmp_path):
    exporter = DossierExporter(base_dir=tmp_path)
    artifacts = exporter.export(markdown="# Title\n\nBody text", base_name="demo")

    assert artifacts.pdf_path is not None and artifacts.pdf_path.exists()
    assert artifacts.html_path is not None and artifacts.html_path.exists()
    assert not artifacts.warnings


def test_signature_manifest_includes_uploaded_hashes(tmp_path):
    now = datetime.now(timezone.utc)
    plan = DossierPlan(
        plan_id="test-plan",
        jurisdiction_key="US-CA",
        created_at=now,
        total_loss_usd=Decimal("50000"),
        cases=[
            DossierCandidate(
                case_id="case-1",
                loss_amount_usd=Decimal("50000"),
                accepted_at=now - timedelta(days=3),
                jurisdiction="US-CA",
                cross_border=False,
                primary_entities=("wallet-1",),
            )
        ],
        bundle_reason="test",
        cross_border=False,
    )

    def uploader(artifacts, plan_arg):  # noqa: ANN001
        assert plan_arg.plan_id == plan.plan_id
        labels = [label for label, _ in artifacts]
        paths = [path for _, path in artifacts]
        assert "signature_manifest" in labels
        assert any(str(path).endswith(".signatures.json") for path in paths)
        return [
            {
                "label": "upload-pdf",
                "remote_ref": "drive-file-123",
                "hash": "abc123",
                "algorithm": "sha256",
                "size_bytes": 42,
            }
        ]

    generator = DossierGenerator(artifact_dir=tmp_path, uploader=uploader)
    result = generator.generate_from_plan(plan)

    manifest_path = next(path for path in result.artifacts if str(path).endswith(".signatures.json"))
    manifest_payload = json.loads(manifest_path.read_text())
    assert "upload-pdf" in manifest_path.read_text()
    assert "drive-file-123" in manifest_path.read_text()
    uploads = manifest_payload.get("uploads") or []
    assert uploads
    assert uploads[0]["label"] == "upload-pdf"
    assert uploads[0]["remote_ref"] == "drive-file-123"


def test_dossier_uploader_returns_hashes(tmp_path):
    file_path = tmp_path / "demo.pdf"
    file_path.write_text("pdf-bytes")
    plan = DossierPlan(
        plan_id="upload-plan",
        jurisdiction_key="US-CA",
        created_at=datetime.now(timezone.utc),
        total_loss_usd=Decimal("1000"),
        cases=[],
        bundle_reason="upload-test",
        cross_border=False,
        shared_drive_parent_id="drive-parent-123",
    )
    local_md5 = hashlib.md5(file_path.read_bytes()).hexdigest()

    class _StubRequest:
        def __init__(self, md5: str, size: int) -> None:
            self._md5 = md5
            self._size = size

        def execute(self):  # noqa: D401 - test stub
            return {
                "id": "file-1",
                "webViewLink": "https://drive.google.com/file/d/file-1/view",
                "md5Checksum": self._md5,
                "size": str(self._size),
            }

    class _StubFiles:
        def __init__(self, md5: str, size: int) -> None:
            self._md5 = md5
            self._size = size

        def create(self, body, media_body, fields, supportsAllDrives):  # noqa: ANN001, D401 - stub
            assert body["parents"] == [plan.shared_drive_parent_id]
            media_name = getattr(media_body, "filename", getattr(media_body, "_filename", ""))
            assert str(media_name or media_body).endswith("demo.pdf")
            return _StubRequest(self._md5, self._size)

    class _StubDrive:
        def __init__(self, md5: str, size: int) -> None:
            self._files = _StubFiles(md5, size)

        def files(self):  # noqa: D401 - stub helper
            return self._files

    uploader = DossierUploader(drive_service=_StubDrive(local_md5, file_path.stat().st_size))

    rows, warnings = uploader.upload([("pdf_report", file_path)], plan)

    assert warnings == []
    assert rows
    upload = rows[0]
    assert upload["remote_ref"].endswith("file-1/view")
    assert upload["hash"] == hashlib.sha256(file_path.read_bytes()).hexdigest()
    assert upload["algorithm"] == "sha256"
    assert upload["size_bytes"] == file_path.stat().st_size
