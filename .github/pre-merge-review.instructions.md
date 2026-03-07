# Pre-Merge Review Checklist

When the user requests a **pre-merge review**, execute every section below
against **all files changed in the current work stream** (use `git diff` or the
file list from the task context). This is a mandatory, comprehensive pass — not
a quick skim.

---

## 1. Coding Standards (ref: `core/.github/general-coding.instructions.md`)

### Type Hints

- Every function/method has **parameter type hints** and a **return type**.
- Use `from __future__ import annotations` where needed for forward refs.
- For expensive runtime-only imports used solely as types (e.g., Playwright
  `Page`), guard with `TYPE_CHECKING`.

### Docstrings & Comments

- **Public** functions, methods, classes, and modules have a Google-style
  docstring with `Args:`, `Returns:`, and `Raises:` sections where applicable.
- **Private** helpers (`_name`) have at least a one-line docstring explaining
  purpose.
- Non-obvious logic has inline comments explaining _why_, not _what_.

### Naming

- Python: `snake_case` functions/variables, `PascalCase` classes, `UPPER_SNAKE_CASE`
  constants.
- TypeScript: `camelCase` variables/functions, `PascalCase` components/types,
  `UPPER_SNAKE_CASE` constants.
- Terraform: `snake_case` everything.

### Formatting

- Python: Black-compatible at 120 chars, isort (profile = black).
- TypeScript: `pnpm format` (Prettier).
- Terraform: `terraform fmt`.

### Imports

- No unused imports.
- Absolute imports preferred in Python. No wildcard imports.

---

## 2. Code Quality

- **No dead code.** Remove commented-out blocks, unused variables, unreachable
  branches.
- **No bare `except:`.** Catch specific exceptions.
- **No hard-coded secrets, paths, or URLs.** Use settings / env vars.
- **Error handling is present** where I/O or external calls occur (try/except
  with logging).
- **Variable scoping is safe** — no variables referenced outside the block where
  they are assigned (e.g., conditional assignments that might not execute).

---

## 3. Architecture & Patterns

- New code follows existing patterns in the codebase (store factories, settings
  access, audit logging).
- No circular imports.
- Database changes have an Alembic migration with a descriptive message and
  idempotent guards.
- Pydantic models use `snake_case` internally with `alias_generator` for wire
  format — no manual casing translation.

---

## 4. Tests

- Changed/new logic has corresponding unit tests.
- Run the full test suite (`pytest tests/unit`) and confirm **zero failures**.
- Note any intentionally skipped test files and the reason.

---

## 4b. Pre-Commit Hooks (repo-specific — mandatory double-pass)

Each repo has its own `.pre-commit-config.yaml` and its own conda environment.
**Always run `pre-commit` through the correct conda env and from that repo's root directory.**
Do NOT run plain `pre-commit` — it will use the wrong Python environment and produce incorrect results.

| Repo    | Conda env   | Command |
|---------|-------------|----------------------------------------------------------|
| `core/` | `i4g`       | `conda run -n i4g pre-commit run --all-files`            |
| `ssi/`  | `i4g-ssi`   | `conda run -n i4g-ssi pre-commit run --all-files`        |

**Procedure for every repo in scope:**

```bash
cd <repo-root>                            # must be the repo containing .pre-commit-config.yaml
conda run -n <env> pre-commit run --all-files   # Pass 1 — formatter hooks auto-fix files
git add -u                                # stage auto-fixed files (black, isort, ruff --fix)
conda run -n <env> pre-commit run --all-files   # Pass 2 — must exit clean, zero files modified
```

- Pass 1 routinely modifies files (Black reformats, isort reorders, ruff auto-fixes). This is expected.
- After Pass 1, **always** `git add -u` the auto-fixed files before Pass 2.
- Pass 2 must show every hook as **Passed** with no files modified. If any hook still fails, fix the root cause — do not re-run in a loop.
- The pre-merge review is **not complete** until a clean Pass 2 is confirmed for every repo that has changes.

---

## 5. Docs & Config

- If behavior or environment variables changed, update:
  - `planning/change_log.md`
  - `docs/config/` (settings manifest / env-var table)
  - Inline docstrings / module docstrings
- Markdown follows present-tense, active-voice, second-person style.

---

## 6. Reporting

After the review, produce a summary:

1. **Issues found** — list each with file, line, and category (e.g., "missing
   docstring", "unused import", "unsafe variable scope").
2. **Fixes applied** — list what was corrected.
3. **Test results** — pass/fail count and any skipped suites.
4. **Remaining items** — anything that could not be auto-fixed and needs human
   decision.
