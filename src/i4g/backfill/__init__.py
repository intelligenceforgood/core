"""Backfill framework — unified coordination for async processing tasks.

This package provides a consistent interface for running reentrant batch
jobs that discover unprocessed items and process them.  Tasks like fraud
classification, SSI auto-investigation, risk-score computation, and
analytics aggregation all fit this pattern.

Key components:

- :mod:`~i4g.backfill.registry` — task definitions and the global registry
- :mod:`~i4g.backfill.lock` — database-backed advisory locks
- :mod:`~i4g.backfill.coordinator` — runs one or more tasks with locking
- :mod:`~i4g.backfill.status` — queries pending-work counts for each task
"""
