# General Coding Guidelines

These are the shared coding standards referenced by `.github/copilot-instructions.md`
in every repository. **Follow the idiomatic conventions of each language/tool --
do not invent project-specific patterns when the ecosystem already has a clear
standard.**

## Universal Principles

- **Consistency over preference.** Match the style of the file and project you
  are editing. When writing new code, follow the language-specific rules below.
- **Configuration-driven code.** Fetch settings through
  `i4g.settings.get_settings()` and honor the environment-aware factories in
  `src/i4g/services/factories.py`. Hard-coded paths, URLs, and credentials are
  never acceptable.
- **ASCII by default.** Keep edits ASCII unless a file already depends on
  Unicode. Never revert user-authored changes without explicit direction.
- **Test before shipping.** Run relevant tests or smoke flows (`pytest
tests/unit`, targeted `tests/adhoc/` scripts, `i4g bootstrap local reset`)
  before shipping changes; note any skipped suites in summaries.
- **Docs in sync.** Material changes update `planning/change_log.md`,
  `docs/design/architecture.md`, or `docs/development/dev_guide.md` as needed.
- **No manual casing translation layers.** When data crosses a language boundary
  (e.g., Python API to TypeScript client), use framework-native serialization
  (Pydantic `alias_generator`, Zod `.transform()`, etc.) rather than writing
  manual field-rename functions. See D79 in `debt_remediation_plan.md`.

---

## Python

- **Type hints:** Required on all new or modified functions (parameters + return).
- **Docstrings:** Google-style. Required on public functions, classes, and
  modules. Concise explanatory comments when logic is non-obvious.
- **Formatter:** Black, 120-char line limit. Import ordering: isort (profile =
  black).
- **Naming:**
  - `snake_case` for functions, variables, methods, module file names.
  - `PascalCase` for classes and type aliases.
  - `UPPER_SNAKE_CASE` for module-level constants.
  - Singular nouns for constants, file names, database tables, and configuration
    keys (e.g., `REPORT_BUCKET`, not `REPORTS_BUCKET`). Avoid plurals unless the
    value is a collection.
- **Pydantic models:** Field names are `snake_case` in Python. When serving JSON
  to non-Python clients, use a `CamelModel` base with `alias_generator = to_camel`
  and `by_alias=True` so the wire format is camelCase without manual mapping.
- **Imports:** Absolute imports preferred (`from i4g.store.review_store import
ReviewStore`). Relative imports only within the same sub-package.
- **Error handling:** Catch specific exceptions. Never bare `except:`. Log
  errors with `logger.exception()` or `logger.error(..., exc_info=True)`.
- **Datetime:** Use `datetime.now(datetime.UTC)`, never `datetime.utcnow()`
  (deprecated Python 3.12+).
- **Logging:** Every module: `logger = logging.getLogger(__name__)`. Use
  structured key-value pairs in log messages (`logger.info("action", extra={...})`
  or f-string with context).

## TypeScript / JavaScript

- **TypeScript required** for all new code. No `.js` files in `ui/` unless
  they are build configs (e.g., `next.config.js`, `tailwind.config.js`).
- **Formatter:** Prettier via `pnpm format`. Always run after editing.
- **Linter:** ESLint with the project config. Zero warnings in CI.
- **Naming:**
  - `camelCase` for variables, functions, object properties, React hooks.
  - `PascalCase` for components, classes, type/interface names, enum members.
  - `UPPER_SNAKE_CASE` for true constants and environment variable references.
  - File names: `kebab-case.ts` for utilities, `PascalCase.tsx` for React
    components (follow whichever convention the enclosing directory already uses).
- **Types:** Favor interfaces over `type` aliases for object shapes. Use
  discriminated unions for variant/status handling. Model data with interfaces
  that mirror FastAPI schemas (camelCase field names matching the Pydantic
  `alias_generator` output).
- **React:** Functional components with hooks only. Use `React.FC` only when
  children are required. Move derived state to custom hooks. Style via CSS
  modules or `@i4g/ui-kit`.
- **Exports:** Named exports preferred. Default exports only for Next.js page
  and layout files (required by framework).
- **Error handling:** Never swallow errors silently. `try/catch` blocks must
  log or surface the error. Use Error boundaries in React.
- **Null handling:** Prefer `undefined` over `null` in new code (unless
  matching an external API contract). Use optional chaining (`?.`) and
  nullish coalescing (`??`).

## HTML / CSS

- **Semantic HTML.** Use `<main>`, `<nav>`, `<section>`, `<article>`, `<button>`
  -- not `<div>` with click handlers.
- **Accessibility.** All interactive elements must be keyboard-reachable. Images
  need `alt` text. Form inputs need `<label>`.
- **CSS Modules** preferred in `ui/`. Avoid inline styles. Use design tokens
  from `@i4g/ui-kit` or `mobile/shared/design-tokens` when available.
- **No `!important`** unless overriding third-party CSS with no other option.

## Terraform / HCL

- **Formatter:** `terraform fmt`. Run before committing.
- **Naming:**
  - `snake_case` for all resource names, variable names, output names, locals.
  - Module directories: `snake_case` or `kebab-case` (match existing convention
    in `infra/modules/`).
- **Variables:** Always include `description` and `type`. Use `default` only
  when a sensible safe default exists; required variables have no default.
- **Sensitive values:** Mark with `sensitive = true`. Never put secrets in
  `.tfvars` -- use Secret Manager references.
- **Outputs:** Provide outputs for any value that downstream modules or the
  console need.
- **File layout per module:** `main.tf`, `variables.tf`, `outputs.tf`. Large
  modules may split into logical files (e.g., `iam.tf`, `networking.tf`).
- **Target `i4g-dev` first.** Never apply to `i4g-prod` without a successful
  dev deployment.

## TOML / YAML / JSON (Config Files)

- **TOML** (`settings.toml`, `pyproject.toml`): `snake_case` keys. Section
  headers in `[brackets]`.
- **YAML** (GitHub Actions, manifests): `snake_case` or `kebab-case` depending
  on the tool's convention. Prefer block scalars over long single-line strings.
- **JSON** (package.json, tsconfig): Follow the tool's required key names.
  Keep formatting consistent with Prettier (`pnpm format`).
- **`.env` files:** `UPPER_SNAKE_CASE` keys. Prefix project env vars with
  `I4G_`. Use double underscores for nested sections (`I4G_LLM__PROVIDER`).

## SQL / Database

- **Table and column names:** `snake_case`, singular (`review_queue`, not
  `ReviewQueues`).
- **Migrations:** Use Alembic. Each migration gets a descriptive message.
  Never modify a migration that has been applied to a shared environment.
- **Queries:** Use SQLAlchemy ORM or Core expressions. Raw SQL only when ORM
  cannot express the query; always use parameterized queries (never string
  interpolation).

## Shell / Bash

- **Use `set -euo pipefail`** at the top of scripts.
- **Quote all variables:** `"$var"`, not `$var`.
- **Naming:** `snake_case` for local variables, `UPPER_SNAKE_CASE` for
  exported env vars.
- **Shebang:** `#!/usr/bin/env bash`.
- **Portability:** Prefer POSIX-compatible constructs. Use `[[ ]]` for
  conditionals and `$()` for command substitution (not backticks).

## Markdown / Documentation

- **Grammar:** Present tense ("is", "runs"), active voice, second person ("you").
  Write factual statements; avoid "could"/"would".
- **Structure:** Use headings, bullet points, and code blocks. Keep lines at most
  120 chars where practical.
- **Code snippets:** Do NOT paste entire source files. Show focused excerpts
  (3-15 lines) with a link to the full file path.

---

## Collaboration & Review

- Treat collaboration as a two-person team (you + Copilot); you own
  prioritization and approvals.
- When preparing to merge, request (or expect) a "picky reviewer" pass: verify
  style conformance (including `pnpm format` for UI, `terraform fmt` for infra),
  remove dead code, ensure tests/docs reflect behavior across all repositories,
  and confirm deployment instructions (e.g., Cloud Run) are accurate.
