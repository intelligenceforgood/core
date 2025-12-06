"""Utilities to export dossier markdown into PDF and HTML artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Iterable, List, Sequence

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


@dataclass(frozen=True)
class ExportArtifacts:
    """Rendered dossier export artifacts."""

    pdf_path: Path | None
    html_path: Path | None
    warnings: Sequence[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "pdf_path": str(self.pdf_path) if self.pdf_path else None,
            "html_path": str(self.html_path) if self.html_path else None,
            "warnings": list(self.warnings),
        }


class DossierExporter:
    """Exports dossier markdown into PDF and HTML formats."""

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._styles = getSampleStyleSheet()
        if "Heading3" not in self._styles:
            self._styles.add(ParagraphStyle(name="Heading3", parent=self._styles["Heading2"], fontSize=12))

    def export(self, *, markdown: str, base_name: str) -> ExportArtifacts:
        """Render markdown into PDF and HTML, returning artifact paths and warnings."""

        warnings: List[str] = []
        pdf_path: Path | None = self._base_dir / f"{base_name}.pdf"
        html_path: Path | None = self._base_dir / f"{base_name}.html"
        self._base_dir.mkdir(parents=True, exist_ok=True)

        try:
            self._render_pdf(markdown=markdown, destination=pdf_path)
        except Exception as exc:  # pragma: no cover - defensive guardrail
            warnings.append(f"PDF export failed: {exc}")
            pdf_path = None

        try:
            self._render_html(markdown=markdown, destination=html_path)
        except Exception as exc:  # pragma: no cover - defensive guardrail
            warnings.append(f"HTML export failed: {exc}")
            html_path = None

        return ExportArtifacts(pdf_path=pdf_path, html_path=html_path, warnings=tuple(warnings))

    def _render_pdf(self, *, markdown: str, destination: Path) -> None:
        document = SimpleDocTemplate(str(destination), pagesize=LETTER)
        story: List[Paragraph | Spacer] = []
        for block in self._split_blocks(markdown):
            story.extend(self._block_to_flowables(block))
            story.append(Spacer(1, 8))
        document.build(story)

    def _render_html(self, *, markdown: str, destination: Path) -> None:
        html_lines: List[str] = [
            "<html><head><meta charset='utf-8'>",
            "<style>"
            "body{font-family:Arial,Helvetica,sans-serif;line-height:1.5;margin:16px;}"
            "h1,h2,h3{margin-top:12px;margin-bottom:4px;}"
            "p{margin:6px 0;}"
            "ul{margin:6px 0 6px 18px;}"
            "</style>",
            "</head><body>",
        ]
        in_list = False
        for line in markdown.splitlines():
            text = escape(line.strip())
            if not text:
                continue
            if text.startswith("# "):
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                html_lines.append(f"<h1>{escape(text[2:].strip())}</h1>")
            elif text.startswith("## "):
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                html_lines.append(f"<h2>{escape(text[3:].strip())}</h2>")
            elif text.startswith("### "):
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                html_lines.append(f"<h3>{escape(text[4:].strip())}</h3>")
            elif text.startswith("- "):
                if not in_list:
                    html_lines.append("<ul>")
                    in_list = True
                html_lines.append(f"<li>{escape(text[2:])}</li>")
            else:
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                html_lines.append(f"<p>{text}</p>")
        if in_list:
            html_lines.append("</ul>")
        html_lines.append("</body></html>")
        destination.write_text("\n".join(html_lines))

    def _block_to_flowables(self, block: str) -> List[Paragraph | Spacer]:
        flowables: List[Paragraph | Spacer] = []
        for line in block.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("# "):
                flowables.append(Paragraph(stripped[2:].strip(), self._styles["Heading1"]))
            elif stripped.startswith("## "):
                flowables.append(Paragraph(stripped[3:].strip(), self._styles["Heading2"]))
            elif stripped.startswith("### "):
                flowables.append(Paragraph(stripped[4:].strip(), self._styles["Heading3"]))
            elif stripped.startswith("- "):
                flowables.append(Paragraph(stripped[2:].strip(), self._styles["Bullet"]))
            else:
                flowables.append(Paragraph(stripped, self._styles["BodyText"]))
        return flowables

    def _split_blocks(self, markdown: str) -> Iterable[str]:
        return markdown.split("\n\n")


__all__ = ["DossierExporter", "ExportArtifacts"]
