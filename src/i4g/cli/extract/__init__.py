"""Extract command group."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import typer

from i4g.cli.extract import tasks

extract_app = typer.Typer(help="OCR and extraction pipelines.")


@extract_app.command("ocr", help="Run OCR pipeline against chat screenshots.")
def extract_ocr(
    input_path: Path = typer.Option(..., "--input", exists=True, readable=True, help="Folder of images."),
    output_path: Path = typer.Option(Path("data/ocr_output.jsonl"), "--output", help="Output JSONL path."),
) -> None:
    code = tasks.ocr(SimpleNamespace(input=input_path, output=output_path))
    if code:
        raise typer.Exit(code)


@extract_app.command("extraction", help="Run extraction pipeline.")
def extract_extraction(
    input_path: Path = typer.Option(Path("data/ocr_output.jsonl"), "--input", help="OCR output JSONL."),
    output_path: Path = typer.Option(Path("data/entities.jsonl"), "--output", help="Structured entities output."),
) -> None:
    code = tasks.extraction(SimpleNamespace(input=input_path, output=output_path))
    if code:
        raise typer.Exit(code)


@extract_app.command("semantic", help="Run semantic extraction pipeline.")
def extract_semantic(
    input_path: Path = typer.Option(Path("data/ocr_output.jsonl"), "--input", help="OCR output JSONL."),
    output_path: Path = typer.Option(
        Path("data/entities_semantic.jsonl"), "--output", help="Semantic entities output."
    ),
    model: str = typer.Option("llama3.1", "--model", help="Semantic extractor model."),
) -> None:
    code = tasks.semantic(SimpleNamespace(input=input_path, output=output_path, model=model))
    if code:
        raise typer.Exit(code)


@extract_app.command("lea-pilot", help="Run LEA pilot pipeline.")
def extract_lea_pilot() -> None:
    code = tasks.lea_pilot(SimpleNamespace())
    if code:
        raise typer.Exit(code)
