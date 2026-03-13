"""Tests for report chart renderers in dossier_visuals.

Covers ReportChartRenderer.render_bar_chart, render_line_chart,
and render_funnel_chart.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from i4g.reports.dossier_visuals import ReportChartRenderer


@pytest.fixture()
def renderer(tmp_path: Path) -> ReportChartRenderer:
    """Create a ReportChartRenderer writing to a temp directory."""
    return ReportChartRenderer(tmp_path / "charts")


# ---------------------------------------------------------------------------
# Bar chart
# ---------------------------------------------------------------------------


def test_bar_chart_creates_file(renderer: ReportChartRenderer) -> None:
    """render_bar_chart produces a PNG file."""
    data = [("Bank Fraud", 50000.0), ("Romance Scam", 30000.0)]
    path = renderer.render_bar_chart(data, title="Test Bar")
    assert path.exists()
    assert path.suffix == ".png"


def test_bar_chart_empty_data(renderer: ReportChartRenderer) -> None:
    """render_bar_chart handles empty data gracefully."""
    path = renderer.render_bar_chart([], title="Empty")
    assert path.exists()


# ---------------------------------------------------------------------------
# Line chart
# ---------------------------------------------------------------------------


def test_line_chart_creates_file(renderer: ReportChartRenderer) -> None:
    """render_line_chart produces a PNG file."""
    series = {
        "proactive": [("W01", 10.0), ("W02", 15.0), ("W03", 12.0)],
        "reactive": [("W01", 5.0), ("W02", 8.0), ("W03", 6.0)],
    }
    path = renderer.render_line_chart(series, title="Velocity")
    assert path.exists()
    assert path.suffix == ".png"


# ---------------------------------------------------------------------------
# Funnel chart
# ---------------------------------------------------------------------------


def test_funnel_chart_creates_file(renderer: ReportChartRenderer) -> None:
    """render_funnel_chart produces a PNG file."""
    stages = [("Intake", 100), ("Triage", 80), ("Actioned", 50)]
    path = renderer.render_funnel_chart(stages, title="Pipeline")
    assert path.exists()
    assert path.suffix == ".png"


def test_funnel_chart_empty_data(renderer: ReportChartRenderer) -> None:
    """render_funnel_chart handles empty data gracefully."""
    path = renderer.render_funnel_chart([], title="Empty Funnel")
    assert path.exists()
