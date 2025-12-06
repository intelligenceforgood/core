"""Lightweight dossier generation scaffolding used by the queue processor."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, List, Mapping, Sequence

from i4g.reports.bundle_builder import DossierPlan
from i4g.reports.dossier_agent_payload import build_agent_payload
from i4g.reports.dossier_analysis import analyze_plan
from i4g.reports.dossier_context import DossierContextLoader, DossierContextResult
from i4g.reports.dossier_exports import DossierExporter, ExportArtifacts
from i4g.reports.dossier_signatures import build_uploaded_signatures, generate_signature_manifest
from i4g.reports.dossier_templates import TemplateRegistry, TemplateRenderResult
from i4g.reports.dossier_tools import DossierToolResults, DossierToolSuite
from i4g.reports.dossier_uploads import DossierUploader
from i4g.reports.dossier_visuals import DossierVisualAssets, DossierVisualBuilder
from i4g.services.factories import build_dossier_context_loader
from i4g.settings import get_settings

UploadResult = Iterable[Mapping[str, object]] | tuple[Iterable[Mapping[str, object]], Sequence[str]]
Uploader = Callable[[Sequence[tuple[str, Path]], DossierPlan], UploadResult]


@dataclass(frozen=True)
class DossierGenerationResult:
    """Container describing generated dossier artifacts."""

    plan_id: str
    artifacts: Sequence[Path]
    warnings: Sequence[str]


class DossierGenerator:
    """Prototype dossier generator that emits JSON manifests for downstream tooling."""

    def __init__(
        self,
        *,
        artifact_dir: Path | None = None,
        context_loader: DossierContextLoader | None = None,
        visuals_builder: DossierVisualBuilder | None = None,
        tool_suite: DossierToolSuite | None = None,
        template_registry: TemplateRegistry | None = None,
        exporter: DossierExporter | None = None,
        uploader: Uploader | None = None,
        tool_timeout_seconds: float | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        settings = get_settings()
        base_dir = artifact_dir or (settings.data_dir / "reports" / "dossiers")
        base_dir.mkdir(parents=True, exist_ok=True)
        self._artifact_dir = base_dir
        self._context_loader = context_loader or build_dossier_context_loader()
        self._visuals_builder = visuals_builder or DossierVisualBuilder(base_dir=base_dir)
        timeout = tool_timeout_seconds if tool_timeout_seconds is not None else settings.report.tool_timeout_seconds
        self._tool_suite = tool_suite or DossierToolSuite(timeout_seconds=timeout)
        self._template_registry = template_registry or TemplateRegistry()
        self._exporter = exporter or DossierExporter(base_dir=base_dir)
        self._uploader = uploader or DossierUploader()
        self._hash_algorithm = settings.report.hash_algorithm
        self._now = now_provider or (lambda: datetime.now(timezone.utc))

    def generate_from_plan(self, plan: DossierPlan) -> DossierGenerationResult:
        """Persist a serialized dossier plan and return the artifact location."""

        payload = plan.to_dict()
        timestamp = self._now()
        payload["generated_at"] = timestamp.isoformat()
        payload["case_count"] = len(plan.cases)
        analysis = analyze_plan(plan)
        payload["analysis"] = analysis.to_dict()
        warnings: List[str] = []
        assets: DossierVisualAssets | None = None
        asset_view: dict | None = None
        context: DossierContextResult | None = None
        tool_results: DossierToolResults | None = None
        template_render: TemplateRenderResult | None = None
        exports: ExportArtifacts | None = None

        if self._context_loader:
            context = self._context_loader.load(plan)
            payload["context"] = context.to_dict()
            warnings.extend(context.warnings)
        else:
            payload["context"] = None

        if self._visuals_builder:
            assets = self._visuals_builder.render(plan)
            asset_view = assets.to_dict(relative_to=self._artifact_dir)
            payload["assets"] = asset_view
            warnings.extend(assets.warnings)
        else:
            payload["assets"] = None

        if self._tool_suite:
            tool_results = self._tool_suite.run(
                plan=plan,
                context=context,
                analysis=analysis,
                assets=assets,
                asset_base=self._artifact_dir,
            )
            payload["tools"] = tool_results.to_dict()
            warnings.extend(tool_results.warnings)
        else:
            payload["tools"] = None

        markdown_path: Path | None = None
        if self._template_registry:
            markdown_path = self._artifact_dir / f"{plan.plan_id}.md"
            template_render = self._template_registry.render(
                destination=markdown_path,
                plan=plan,
                analysis=analysis,
                context=context,
                tool_results=tool_results,
                assets=assets,
                asset_base=self._artifact_dir,
            )
            template_payload = template_render.to_dict()
            template_path = template_payload.get("path")
            if template_path:
                template_payload["path"] = self._relativize_path(Path(template_path))
            payload["template_render"] = template_payload
            warnings.extend(template_render.warnings)
        else:
            payload["template_render"] = None

        if template_render and template_render.markdown:
            exports = self._exporter.export(markdown=template_render.markdown, base_name=plan.plan_id)
            export_payload = exports.to_dict()
            if exports.pdf_path:
                export_payload["pdf_path"] = self._relativize_path(exports.pdf_path)
            if exports.html_path:
                export_payload["html_path"] = self._relativize_path(exports.html_path)
            payload["exports"] = export_payload
            warnings.extend(exports.warnings)
        else:
            payload["exports"] = None

        destination = self._artifact_dir / f"{plan.plan_id}.json"
        signature_path = destination.with_suffix(".signatures.json")
        payload["signature_manifest"] = {
            "path": self._relativize_path(signature_path),
            "algorithm": self._hash_algorithm,
        }

        payload["agent_payload"] = build_agent_payload(plan=plan, context=context, analysis=analysis).to_dict()

        destination.write_text(json.dumps(payload, indent=2))

        signature_entries = [("manifest", destination)]
        if markdown_path and markdown_path.exists():
            signature_entries.append(("markdown_report", markdown_path))
        if exports:
            if exports.pdf_path and exports.pdf_path.exists():
                signature_entries.append(("pdf_report", exports.pdf_path))
            if exports.html_path and exports.html_path.exists():
                signature_entries.append(("html_report", exports.html_path))
        if assets:
            signature_entries.extend(
                [
                    ("timeline_chart", assets.timeline_chart),
                    ("geo_map_image", assets.geo_map_image),
                    ("geojson", assets.geojson_path),
                ]
            )
        upload_entries: list[tuple[str, Path]] = [(label, path) for label, path in signature_entries if path]
        upload_entries.append(("signature_manifest", signature_path))
        signature_manifest = generate_signature_manifest(
            signature_entries,
            algorithm=self._hash_algorithm,
            generated_at=timestamp,
            relative_to=self._artifact_dir,
        )
        signature_path.write_text(json.dumps(signature_manifest.to_dict(), indent=2))
        warnings.extend(signature_manifest.warnings)

        upload_rows: list[Mapping[str, object]] = []
        upload_warnings: list[str] = []
        if self._uploader:
            try:
                upload_rows, upload_warnings = self._execute_upload(upload_entries, plan)
            except Exception as exc:  # pragma: no cover - defensive guardrail
                warnings.append(f"Upload step failed: {exc}")
        if upload_rows:
            uploaded_signatures, signature_warnings = build_uploaded_signatures(
                upload_rows,
                default_algorithm=self._hash_algorithm,
            )
            signature_manifest = signature_manifest.with_uploads(
                uploaded_signatures,
                warnings=signature_warnings,
            )
            signature_path.write_text(json.dumps(signature_manifest.to_dict(), indent=2))
            warnings.extend(signature_warnings)
        if upload_warnings:
            warnings.extend(upload_warnings)

        artifacts = [destination, signature_path]
        if markdown_path:
            artifacts.append(markdown_path)
        if exports:
            if exports.pdf_path:
                artifacts.append(exports.pdf_path)
            if exports.html_path:
                artifacts.append(exports.html_path)
        return DossierGenerationResult(plan_id=plan.plan_id, artifacts=artifacts, warnings=warnings)

    def _execute_upload(
        self,
        entries: Sequence[tuple[str, Path]],
        plan: DossierPlan,
    ) -> tuple[list[Mapping[str, object]], list[str]]:
        if self._uploader is None:
            return [], []
        if isinstance(self._uploader, DossierUploader):
            raw_result = self._uploader.upload(entries, plan)
        else:
            raw_result = self._uploader(entries, plan)
        if isinstance(raw_result, tuple) and len(raw_result) == 2:
            rows_iter, upload_warnings = raw_result
            rows = list(rows_iter or [])
            warnings = list(upload_warnings or [])
        else:
            rows = list(raw_result or [])
            warnings = []
        return rows, warnings

    def _relativize_path(self, path: Path | None) -> str | None:
        if not path:
            return None
        resolved = Path(path)
        try:
            return str(resolved.resolve().relative_to(self._artifact_dir))
        except (FileNotFoundError, ValueError):
            return str(resolved.resolve())
