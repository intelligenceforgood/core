"""Phase C / D-local smoke harness for the merklemap-tail ingest job.

This script is a NO-CLOUD, operator-run rehearsal tool.  It does NOT execute
Docker — it validates your local environment and prints the exact ``docker run``
command you should run after building the ``ingest-job:dev`` image.

Prerequisites
-------------
1. Build the ingest-job image::

       scripts/build_image.sh ingest-job dev

2. Export a real (or dev) Merklemap API key::

       export PHISHDESTROY__MERKLEMAP_TAIL__API_KEY=<your-key>

3. Run this script::

       python scripts/smoke_merklemap_tail_local.py

4. Copy the printed ``docker run`` command and execute it.  Watch for
   ``merklemap-tail counters`` lines in the container logs confirming events
   were received.

Phase D2 note
-------------
When GCP billing on ``i4g-dev`` is restored, the Cloud Run smoke in Phase D2
supersedes this local harness.  This script remains as a developer convenience
and CI-gate rehearsal aid.
"""

from __future__ import annotations

import os
import sys


def main() -> None:
    """Validate environment and print the operator-run docker command.

    Reads ``PHISHDESTROY__MERKLEMAP_TAIL__API_KEY`` from the environment.
    Exits with code 2 if the key is missing or empty.

    Args:
        None — reads environment variables directly.
    """
    api_key = os.environ.get("PHISHDESTROY__MERKLEMAP_TAIL__API_KEY", "").strip()
    if not api_key:
        print(
            "ERROR: PHISHDESTROY__MERKLEMAP_TAIL__API_KEY is not set or empty.\n"
            "Export the key before running this script:\n\n"
            "    export PHISHDESTROY__MERKLEMAP_TAIL__API_KEY=<your-key>\n",
            file=sys.stderr,
        )
        sys.exit(2)

    image = "ingest-job:dev"
    env_file = ".env.local"

    cmd_lines = [
        "docker run \\",
        "  --rm \\",
        "  --platform=linux/amd64 \\",
        f"  --env-file={env_file} \\",
        f"  --env PHISHDESTROY__MERKLEMAP_TAIL__API_KEY={api_key} \\",
        "  --env I4G_ENV=local \\",
        "  --env I4G_PHISHDESTROY__MERKLEMAP_TAIL__ENABLED=true \\",
        "  # --network=host  # uncomment if connecting to localhost:5432 Postgres",
        f"  {image} \\",
        "  jobs merklemap-tail \\",
        "  --max-runtime-seconds=60 \\",
        "  --max-events=5",
    ]

    print("=" * 72)
    print("Phase D-local smoke — merklemap-tail ingest job")
    print("=" * 72)
    print()
    print("Prerequisites: `scripts/build_image.sh ingest-job dev` must have")
    print(f"completed successfully and produced the `{image}` image.")
    print()
    print("Docker run command (copy and execute):")
    print()
    for line in cmd_lines:
        print(line)
    print()
    print(
        "Operator: copy the docker run command above and execute it; "
        "review logs for 'merklemap-tail counters' lines."
    )


if __name__ == "__main__":
    main()
