"""Legacy shim for saved-search tagging helpers.

The implementation now lives in ``i4g.cli.saved_search_helpers`` so CLI commands
can import it directly. This module remains to avoid breaking older imports.
"""

from __future__ import annotations

from i4g.cli import saved_search_helpers as _helpers

# Mirror the SETTINGS symbol for backward-compatible monkeypatching in tests.
SETTINGS = _helpers.SETTINGS


def build_argument_parser():  # noqa: D401
    """Return the CLI argument parser for the tagging helper."""

    # Keep shim-level monkeypatches in sync with the helper module.
    _helpers.SETTINGS = SETTINGS
    return _helpers.build_argument_parser()


def annotate_records(*args, **kwargs):  # noqa: D401
    """Delegate to helper implementation."""

    return _helpers.annotate_records(*args, **kwargs)


def annotate_file(*args, **kwargs):  # noqa: D401
    """Delegate to helper implementation."""

    return _helpers.annotate_file(*args, **kwargs)


def load_records(*args, **kwargs):  # noqa: D401
    """Delegate to helper implementation."""

    return _helpers.load_records(*args, **kwargs)


def main():  # noqa: D401
    """Delegate to helper implementation."""

    _helpers.SETTINGS = SETTINGS
    return _helpers.main()


__all__ = [
    "annotate_records",
    "annotate_file",
    "build_argument_parser",
    "load_records",
    "main",
]
