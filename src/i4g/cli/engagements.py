"""CLI commands for engagement management."""

from __future__ import annotations

import logging
from typing import Annotated

import typer

logger = logging.getLogger(__name__)

engagements_app = typer.Typer(help="Engagement management — create, list, and bulk-assign cases.")


@engagements_app.command("assign", help="Bulk-assign existing cases to an engagement.")
def assign_cases(
    engagement_id: Annotated[str, typer.Argument(help="Target engagement ID.")],
    case_ids: Annotated[list[str] | None, typer.Option("--case-id", help="Case IDs to assign.")] = None,
    dataset: Annotated[str | None, typer.Option("--dataset", help="Assign all cases from this dataset.")] = None,
    before: Annotated[str | None, typer.Option("--before", help="Assign cases created before this ISO date.")] = None,
    after: Annotated[str | None, typer.Option("--after", help="Assign cases created after this ISO date.")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Print matches without updating.")] = False,
) -> None:
    """Assign existing cases to an engagement by ID list, dataset, or date range."""
    from datetime import datetime

    import sqlalchemy as sa

    from i4g.store import sql as sql_schema
    from i4g.store.sql import session_factory as build_sql_session_factory

    sf = build_sql_session_factory()
    with sf() as session:
        # Verify engagement exists
        eng = session.execute(
            sa.select(sql_schema.engagements.c.engagement_id).where(
                sql_schema.engagements.c.engagement_id == engagement_id
            )
        ).scalar()
        if not eng:
            typer.echo(f"Engagement {engagement_id} not found.", err=True)
            raise typer.Exit(1)

        # Build filter
        query = sa.select(sql_schema.cases.c.case_id).where(sql_schema.cases.c.is_deleted.is_(False))

        if case_ids:
            query = query.where(sql_schema.cases.c.case_id.in_(case_ids))
        if dataset:
            query = query.where(sql_schema.cases.c.dataset == dataset)
        if after:
            query = query.where(sql_schema.cases.c.created_at >= datetime.fromisoformat(after))
        if before:
            query = query.where(sql_schema.cases.c.created_at <= datetime.fromisoformat(before))

        rows = session.execute(query).scalars().all()
        typer.echo(f"Found {len(rows)} matching case(s).")

        if dry_run:
            for cid in rows[:20]:
                typer.echo(f"  {cid}")
            if len(rows) > 20:
                typer.echo(f"  ... and {len(rows) - 20} more")
            return

        if not rows:
            return

        session.execute(
            sa.update(sql_schema.cases).where(sql_schema.cases.c.case_id.in_(rows)).values(engagement_id=engagement_id)
        )
        session.commit()
        typer.echo(f"Assigned {len(rows)} case(s) to engagement {engagement_id}.")
