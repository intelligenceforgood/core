"""Legacy admin helpers bridged to the Typer CLI modules.

This shim keeps backward-compatible entry points for saved-search and dossier workflows
while delegating to the newer helpers under ``i4g.cli``.
"""

from __future__ import annotations

import warnings

from i4g.cli import dossiers, pilot, saved_searches, search
from i4g.services.factories import build_review_store
from i4g.settings import get_settings

# Mirror the legacy warning suppression to avoid noisy third-party logs.
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

SETTINGS = get_settings()

# Saved-search helpers
export_saved_searches = saved_searches.export_saved_searches
import_saved_searches = saved_searches.import_saved_searches
prune_saved_searches = saved_searches.prune_saved_searches
bulk_update_saved_search_tags = saved_searches.bulk_update_saved_search_tags
export_tag_presets = saved_searches.export_tag_presets
import_tag_presets = saved_searches.import_tag_presets

# Dossier helpers
build_dossiers = dossiers.build_dossiers
process_dossiers = dossiers.process_dossiers
schedule_pilot_dossiers = pilot.schedule_pilot_dossiers
DEFAULT_PILOT_CASES_PATH = pilot.DEFAULT_PILOT_CASES_PATH

# Query helpers
run_query = search.run_query
run_vertex_search = search.run_vertex_search

__all__ = [
    "SETTINGS",
    "build_review_store",
    "export_saved_searches",
    "import_saved_searches",
    "prune_saved_searches",
    "bulk_update_saved_search_tags",
    "export_tag_presets",
    "import_tag_presets",
    "build_dossiers",
    "process_dossiers",
    "schedule_pilot_dossiers",
    "run_query",
    "run_vertex_search",
    "DEFAULT_PILOT_CASES_PATH",
]
