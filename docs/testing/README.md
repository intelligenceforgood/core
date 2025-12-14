# Testing and TDD

How we design, write, and run tests across the stack.

## Core guidance
- TDD approach and patterns: [../tdd.md](../tdd.md)
- Unit and contract tests: follow module-level guidance; prefer deterministic fixtures and seeded data.
- Settings/env coverage: mirror new env vars in `tests/unit/settings/` and refresh config manifests.
- Smokes: see [../cookbooks/smoke_test.md](../cookbooks/smoke_test.md) for quick validation.
- Frontend E2E: run the Playwright suite in [ui/apps/web](ui/apps/web) and follow [ui/docs/developer-guide.md](ui/docs/developer-guide.md) when API contracts or search UX change.

## What to add next
- E2E/search and ingestion test checklists
- Fixture patterns for ingestion payloads and SQL dual-write
- Playbook for regenerating golden data
