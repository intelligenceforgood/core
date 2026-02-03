import sys
from pathlib import Path
import json

# Add source to path
sys.path.append(str(Path(__file__).parents[3] / "src"))

from i4g.api.dashboard import get_dashboard_overview
from i4g.settings import get_settings


def test_dashboard():
    print("Testing get_dashboard_overview()...")
    settings = get_settings()
    print(f"Backend: {settings.storage.structured_backend}")
    print(f"SQLite Path: {settings.storage.sqlite_path}")

    try:
        data = get_dashboard_overview()
        print("Success! Data returned:")
        print(json.dumps(data, indent=2, default=str))
    except Exception as e:
        print(f"Failed: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    test_dashboard()
