"""Shared CLI utilities and console wiring."""

from __future__ import annotations

import os
import warnings

from rich.console import Console

from i4g.settings import get_settings

# Fix for OpenMP runtime conflict on macOS.
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

console = Console()
SETTINGS = get_settings()

# Quiet noisy third-party warnings during CLI invocations.
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

__all__ = ["console", "SETTINGS"]
