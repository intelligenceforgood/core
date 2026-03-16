"""Evidence storage path sharding utility."""

from __future__ import annotations


def evidence_path(scan_id: str) -> str:
    """Convert scan UUID to sharded evidence storage path.

    Uses 2-level hex prefix sharding (65,536 shards) for even distribution.

    Args:
        scan_id: UUID string (with dashes) identifying the scan.

    Returns:
        Sharded path string, e.g.
        ``'scans/fd/70/fd70a83f-91de-4533-9506-ebe3916dbff9'``.
    """
    hex_str = scan_id.replace("-", "").lower()
    return f"scans/{hex_str[:2]}/{hex_str[2:4]}/{scan_id}"
