"""Saved-search and tagging helpers."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from i4g.api.review import SavedSearchImportRequest
from i4g.cli.utils import SETTINGS, console
from i4g.services.factories import build_review_store


def export_saved_searches(args: Any) -> None:
    """Dump saved searches to JSON."""

    store = build_review_store()
    owner_filter = None if args.all else (args.owner or None)
    records = store.list_saved_searches(owner=owner_filter, limit=args.limit)
    include_tags = {t.strip().lower() for t in (args.include_tags or []) if t.strip()}
    if include_tags:
        records = [r for r in records if include_tags.intersection({t.lower() for t in (r.get("tags") or [])})]
    schema_version = args.schema_version.strip() if getattr(args, "schema_version", None) else ""
    for record in records:
        record.pop("created_at", None)
        if record.get("tags") is None:
            record["tags"] = []
        if schema_version:
            params = record.get("params") or {}
            if isinstance(params, dict):
                params["schema_version"] = schema_version
                record["params"] = params
    if args.split and args.output:
        base = Path(args.output)
        base.mkdir(parents=True, exist_ok=True)
        by_owner: dict[str, list[dict[str, object]]] = {}
        for record in records:
            owner = record.get("owner") or "shared"
            by_owner.setdefault(owner, []).append(record)
        for owner, rows in by_owner.items():
            fname = base / f"saved_searches_{owner}.json"
            fname.write_text(json.dumps(rows, indent=2))
            console.print(f"[green]✅ Exported {len(rows)} saved search(es) to {fname}")
    else:
        data = json.dumps(records, indent=2)
        if args.output:
            Path(args.output).write_text(data)
            console.print(f"[green]✅ Exported {len(records)} saved search(es) to {args.output}")
        else:
            console.print(data)


def import_saved_searches(args: Any) -> None:
    """Load saved searches from JSON file/stdin."""

    store = build_review_store()
    content = Path(args.input).read_text() if args.input else sys.stdin.read()
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        console.print(f"[red]❌ Invalid JSON:[/red] {exc}")
        sys.exit(1)

    include_tags = {t.strip().lower() for t in (args.include_tags or []) if t.strip()}
    items = payload if isinstance(payload, list) else [payload]
    imported = 0
    skipped = 0
    for item in items:
        try:
            req = SavedSearchImportRequest(**item)
            if include_tags and not include_tags.intersection({t.lower() for t in (req.tags or [])}):
                skipped += 1
                continue
            store.import_saved_search(req.model_dump(), owner=None if args.shared else args.owner)
            imported += 1
        except Exception as exc:  # pragma: no cover - defensive logging
            skipped += 1
            console.print(f"[yellow]Skipped #{imported + skipped}: {exc}[/yellow]")
    console.print(f"[green]✅ Imported {imported} saved search(es); {skipped} skipped.")


def prune_saved_searches(args: Any) -> None:
    """Delete saved searches by owner/tag filters."""

    store = build_review_store()
    records = store.list_saved_searches(owner=args.owner, limit=1000)
    tags_filter = {t.strip().lower() for t in (args.tags or []) if t.strip()}
    to_delete = []
    for record in records:
        tags = {t.lower() for t in (record.get("tags") or [])}
        if tags_filter and not tags_filter.intersection(tags):
            continue
        to_delete.append(record)

    if not to_delete:
        console.print("[yellow]No saved searches matched the criteria.")
        return

    for record in to_delete:
        owner = record.get("owner") or "shared"
        console.print(f"[cyan]- {record.get('name')} (owner={owner}, tags={record.get('tags')})")

    if args.dry_run:
        console.print(f"[green]Dry run: {len(to_delete)} saved search(es) would be deleted.")
        return

    deleted = 0
    for record in to_delete:
        if store.delete_saved_search(record["search_id"]):
            deleted += 1
    console.print(f"[green]✅ Deleted {deleted} saved search(es).")


def bulk_update_saved_search_tags(args: Any) -> None:
    """Add, remove, or replace saved-search tags in bulk."""

    if not any([args.add, args.remove, args.replace is not None]):
        console.print("[red]Provide --add, --remove, or --replace to adjust tags.[/red]")
        sys.exit(1)

    if args.replace is not None and (args.add or args.remove):
        console.print("[yellow]⚠️ --replace overrides --add/--remove; add/remove values will be ignored.[/yellow]")

    store = build_review_store()
    normalized_add = [t.strip() for t in (args.add or []) if t.strip()]
    normalized_remove = [t.strip() for t in (args.remove or []) if t.strip()]
    normalized_replace = [t.strip() for t in (args.replace or []) if t.strip()] if args.replace is not None else None

    summary_records = []
    target_ids = []

    if args.search_id:
        target_ids = [sid for sid in args.search_id if sid.strip()]
        for sid in target_ids:
            record = store.get_saved_search(sid)
            if record:
                summary_records.append(record)
    else:
        records = store.list_saved_searches(owner=args.owner, limit=args.limit)
        tags_filter = {t.strip().lower() for t in (args.tags or []) if t.strip()}
        if tags_filter:
            records = [r for r in records if tags_filter.intersection({t.lower() for t in (r.get("tags") or [])})]
        summary_records = records
        target_ids = [r["search_id"] for r in records]

    target_ids = list(dict.fromkeys(target_ids))

    if not target_ids:
        console.print("[yellow]No saved searches matched the criteria.")
        return

    if args.search_id:
        found_ids = {record["search_id"] for record in summary_records}
        missing_ids = [sid for sid in target_ids if sid not in found_ids]
        if missing_ids:
            console.print(
                "[yellow]Warning:[/yellow] the following saved search ID(s) were not found and will be skipped: "
                + ", ".join(missing_ids)
            )

    if args.dry_run:
        console.print(f"[green]Dry run:[/green] would update {len(target_ids)} saved search(es).")
        for record in summary_records[:10]:
            owner = record.get("owner") or "shared"
            console.print(f"  - {record.get('name')} (owner={owner}, tags={record.get('tags') or []})")
        if len(summary_records) > 10:
            console.print(f"  ...and {len(summary_records) - 10} more.")
        return

    updated = store.bulk_update_tags(
        target_ids,
        add=normalized_add,
        remove=normalized_remove,
        replace=normalized_replace,
    )
    console.print(f"[green]✅ Updated tags for {updated} saved search(es).")


def export_tag_presets(args: Any) -> None:
    """Export tag presets derived from saved searches."""

    store = build_review_store()
    presets = store.list_tag_presets(owner=args.owner, limit=1000)
    data = json.dumps(presets, indent=2)
    if args.output:
        Path(args.output).write_text(data)
        console.print(f"[green]✅ Exported {len(presets)} tag preset(s) to {args.output}")
    else:
        console.print(data)


def import_tag_presets(args: Any) -> None:
    """Import tag presets and append as filter presets."""

    content = Path(args.input).read_text() if args.input else sys.stdin.read()
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        console.print(f"[red]❌ Invalid JSON:[/red] {exc}")
        sys.exit(1)
    items = payload if isinstance(payload, list) else [payload]
    presets = []
    for item in items:
        tags = item.get("tags") or []
        if tags and tags not in presets:
            presets.append(tags)
    if not presets:
        console.print("[yellow]No tag presets found in input.")
        return
    output = json.dumps(presets, indent=2)
    if args.input:
        Path(args.input).write_text(output)
        console.print(f"[green]✅ Normalized {len(presets)} tag preset(s).")
    else:
        console.print(output)


__all__ = [
    "export_saved_searches",
    "import_saved_searches",
    "prune_saved_searches",
    "bulk_update_saved_search_tags",
    "export_tag_presets",
    "import_tag_presets",
]
