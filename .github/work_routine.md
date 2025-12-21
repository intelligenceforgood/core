# Work Routine (core)

Use this to rehydrate quickly after restarts and keep collaboration consistent. Follow alongside the per-repo
instructions and planning prompts listed below.

## Instruction Preload (read these every session)
- [core/.github/work_routine.md](work_routine.md)
- [core/.github/copilot-instructions.md](copilot-instructions.md)
- [core/.github/chat-instructions.md](chat-instructions.md)
- [core/.github/general-coding.instructions.md](general-coding.instructions.md)
- [core/.github/docs.instructions.md](docs.instructions.md)

## Rehydrate First
- Check status: `git status -sb` in `core/`.
- Skim [planning/change_log.md](../planning/change_log.md) for recent decisions.
- Re-open [planning/copilot_prompt/persistent_prompt.md](../planning/copilot_prompt/persistent_prompt.md) for norms and
  [planning/copilot_prompt/COPILOT_SESSION.md](../planning/copilot_prompt/COPILOT_SESSION.md) to append session notes.
- Confirm env: `conda run -n i4g python -V`; use `I4G_PROJECT_ROOT=$PWD` and set `I4G_ENV` (`local` for laptop, `dev`/`prod`
  for cloud work).

## Working Norms
- Config: always load settings via `i4g.settings.get_settings()`; override with `I4G_*` env vars (double underscores for
  nesting). Keep store creation through `src/i4g/services/factories.py`.
- Code style: full type hints, Google-style docstrings, Black/isort, ≤120-char lines, ASCII-only unless the file already
  needs Unicode. Do not revert user edits without direction.
- Data/secrets: prefer `.env.local` for local secrets; managed secrets via Secret Manager. Refresh sandbox data with
  `i4g bootstrap local reset --report-dir data/reports/local_bootstrap` when needed.

## Model + Tool Picker (from workflow guide)
- Copilot: IDE automation, incremental coding, Next.js/FastAPI small changes.
- ChatGPT Codex (web): architecture/refactors, multi-file changes.
- Gemini: GCP/IAM/VPC/Cloud Run specifics.

## Daily Loop
- Plan: note the active task and next step in
  [planning/copilot_prompt/COPILOT_SESSION.md](../planning/copilot_prompt/COPILOT_SESSION.md).
- Build: run `uvicorn i4g.api.app:app --reload` for API dev; use the Conda env (`conda run -n i4g ...`).
- Test: for code changes run `pytest tests/unit`; add targeted smokes as needed (e.g., ingestion/report jobs). If skipping
  tests, record it in the summary.
- Docs: when behavior or env vars change, update the relevant doc (architecture/config) and the change log. Keep snippets
  short with links to full files.
- Wrap-up: update COPILOT_SESSION with what happened + next step; ensure `planning/change_log.md` reflects decisions.

## Quick References
- Prompts: [planning/copilot_prompt/i4g_copilot_prompts_full.md](../planning/copilot_prompt/i4g_copilot_prompts_full.md),
  [planning/copilot_prompt/i4g_quick_prompts.md](../planning/copilot_prompt/i4g_quick_prompts.md),
  [planning/copilot_prompt/i4g_workflow_guide_full.md](../planning/copilot_prompt/i4g_workflow_guide_full.md).
- Instruction sources: [core/.github/copilot-instructions.md](copilot-instructions.md) and
  [core/.github/general-coding.instructions.md](general-coding.instructions.md) for style details.

## When Updating Settings or Jobs
- Adjust defaults via config + env vars, not hard-coded paths; add/extend tests under `tests/unit/settings/` for new
  overrides.
- Reflect env var changes in docs under `docs/config/` and rerun the local smoke if jobs are touched:
  `conda run -n i4g I4G_PROJECT_ROOT=$PWD I4G_ENV=dev I4G_LLM__PROVIDER=mock i4g jobs account ...`.
