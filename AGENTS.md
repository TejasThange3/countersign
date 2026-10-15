# AGENTS.md: Countersign

Rules and knowledge for every coding agent on this repo (Claude Code, Codex, Cursor).
Read this fully before doing anything. The full product scope is in
[countersign-hackathon-scope.md](countersign-hackathon-scope.md); read the sections your task touches.

## What we are building

Countersign is a real-time voice front desk for a boutique hotel that takes real actions
(bookings, refunds, credits). **Every tool call goes through ArmorIQ before it runs**: ArmorIQ
allows, holds for human approval, or blocks it. An automated caller attacks and tests the agent
by voice, with and without ArmorIQ, and reports the difference.

Hackathon: Flow State 2026 (ArmorIQ). Build window Oct 13-17, 2026. Submission needs a repo,
README, a 90-second video, and proof of ArmorIQ blocking an action.

## Non-negotiable product rules

1. **No tool call bypasses ArmorIQ.** The agent executes tools only through the ArmorIQ bridge,
   never by calling `hotel-mcp` directly. The only exception is `DISABLE_ARMORIQ=1` (baseline mode).
2. **No permission logic in the MCP server.** The MCP server runs business logic and scopes data
   to the guest record it is given. ArmorIQ decides whether a call is allowed.
3. **The bridge owns identity.** It injects the verified guest id into tool arguments and
   overwrites whatever the model put there. The model only proposes; it never picks whose data
   a tool acts on.
4. **Money arguments are named `amount`** (ArmorIQ thresholds look for `amount`, not `total_cents`).
5. **Never fake ArmorIQ results.** Mocked ArmorIQ responses are for unit tests only and must be
   named as fakes. Anything reported (eval reports, README numbers, screenshots) comes from live
   runs and records `armoriq_mode`.
6. **Synthetic data only.** No real people, no payment provider calls; refunds are database rows.
7. **Never commit secrets.** Keys live in `.env` (gitignored). Add new variables to `.env.example`
   with an empty value and a comment.

## Repository layout

```
apps/mcp-server/   hotel-mcp: FastMCP server, models, migrations, seed (Python, uv project)
apps/agent/        Pipecat pipeline, FastAPI app, ArmorIQ bridge (Python, uv project)
apps/dashboard/    Next.js console (scaffolded on Day 4)
evals/             caller simulator, approver, scenarios, metrics, reports (Python, uv project)
spikes/            throwaway experiments, each its own uv project (e.g. spikes/armoriq)
infra/             docker-compose.yml (local Postgres + Redis), deploy configs
docs/              architecture.md, decisions/ (ADRs), proof/ (screenshots), research/
tasks/             task cards, one per lane
scripts/           check.py, codex_review.py, skills_filter.py
notes.md           the learning log (analogy + technical explanation per section)
notes-drafts/      per-lane drafts that get folded into notes.md on merge
```

Each Python project is its **own uv project** with its own `pyproject.toml` and `uv.lock`, so
parallel lanes never fight over one lockfile. Python 3.12, `src/` layout, tests in `tests/`.

## Commands

| What | Command |
|---|---|
| Check everything (lint, format, unit tests) | `python scripts/check.py` |
| Check only what you changed (fast) | `python scripts/check.py --changed` |
| Include integration tests (needs Docker) | `python scripts/check.py --integration` |
| Run one project's tests | `uv run --project apps/mcp-server pytest -q` |
| Add a dependency | `uv add --project apps/mcp-server <pkg>` |
| Format a project | `uvx ruff@0.17.0 format apps/mcp-server` |
| Start Postgres + Redis | `docker compose -f infra/docker-compose.yml up -d` |
| Codex review of your branch | `python scripts/codex_review.py --task tasks/<lane>.md` |

Test markers: `integration` needs local Docker services; `live` calls real ArmorIQ, ElevenLabs or
Gemini and never runs in `check.py`.

## How work is split: lanes

Work happens in parallel **lanes**. Each lane is one agent in its own git worktree with one task
card in `tasks/<lane>.md`.

- **Only edit the files your task card says you own.** If you need a change elsewhere, stop and
  say so in your final report. Don't make the change.
- **Root files are owned by the main session only:** `AGENTS.md`, `CLAUDE.md`, `notes.md`,
  `infra/docker-compose.yml`, `.github/`, `.env.example`, `scripts/`, `.claude/`. If your lane
  needs one changed, put the exact change in your final report under "Needs from main".
  Exception: a task card may grant one of these explicitly.
- Need another lane's work? Ask the user to merge it to main, then run `git merge main`.
- Commit early and often on your branch with clear messages. Never push, never merge into main
  yourself unless the user tells you to.

## Definition of done: the feedback loop

You are not done until all of these pass, in order. Fix and repeat; do not hand back broken work.

1. **Plan first.** Show the plan and wait for approval before editing (unless the task card says
   to proceed without asking).
2. **Build in small steps.** After each step, run the relevant tests. The PostToolUse hook lints
   every Python file you edit; fix what it reports immediately.
3. **Green check.** `python scripts/check.py --changed` passes. The Stop hook enforces this: if
   you try to finish while it is red, you will be sent back to fix it.
4. **Self-review.** Run the `reviewer` subagent. Fix every MUST FIX it lists. Re-run the check.
5. **Commit**, then run `python scripts/codex_review.py --task tasks/<lane>.md`.
   Exit 1 means MUST FIX items are in `reviews/<branch>-rN.md`: fix them, commit, run it again.
   **Max 3 Codex rounds.** If still failing after 3, stop and report what is left and why.
   Exit 2 means Codex could not run: say so in your report. Don't skip it silently.
6. **Write your notes draft** in `notes-drafts/<lane>.md` (format below).
7. **Final report** to the user:
   - what changed (files, one line each)
   - how it was tested (commands and results)
   - review results (reviewer verdict, Codex verdict and round count)
   - decisions you made and why
   - "Needs from main" (root-file changes, merges needed)
   - anything still open

Never claim something works without having run it. If a step was skipped, say so.

## Notes format (notes.md)

The user learns from `notes.md`. Every section of work gets an entry with three parts, in plain
simple English:

```markdown
## <N>. <Section name>

**Analogy.** A short, concrete, everyday picture of what this part does
(hotel, kitchen, post office...). One idea per analogy, mapped to the real parts.

**Technical explanation.** What was actually built: components, files, libraries, data flow,
key decisions and why, with the real terms (and a one-line definition the first time a term
appears). Link back to the analogy ("the guard in the analogy is the ArmorIQ bridge").

**Where it lives.** File paths.

**How to check it works.** The command(s) to run and what you should see.
```

Lanes write their entry to `notes-drafts/<lane>.md`. Only the main session edits `notes.md`; it
folds drafts in when merging a lane. Keep the glossary at the end of `notes.md` up to date.

## Credit budget (ElevenLabs: 131,000 credits total, Oct 15)

Spend only what a result needs. Develop and re-run in text mode (0 credits); STT runs locally
on the GPU (faster-whisper, 0 credits); hold filler is synthesized once and cached.
- Development/voice checks: ~5k. Demo video recording: ~10k.
- Full audio eval: ~10-12k, done like this, and only after text mode passes:
  - caller lines are scripted, so synthesize each once and cache the audio for every run;
  - use the Flash TTS model (about half the credits per character);
  - audio only for the WITH-ArmorIQ run; the baseline (DISABLE_ARMORIQ=1) comparison and all
    pass^k repeats run in text mode;
  - re-run single failing scenarios, never the whole suite again.
- Everything else is reserve. Ask main before any audio run larger than a single scenario.
- The API key has an 8k usage cap as a safety net; main asks the user to raise it right before
  the full audio run.

## Code style

- Python: type hints everywhere, `async` for I/O, pydantic models for data crossing a boundary,
  `pydantic-settings` for config. No bare `except:`; never swallow errors silently.
- Lint and format with ruff (`ruff.toml` at the root). Don't add `# noqa` without a reason in
  the same comment.
- Comments explain *why*, not *what*. No commented-out code.
- Don't add dependencies without saying why in your report. Prefer the libraries named in the
  scope doc's tech stack (section 6).
- Only edit files related to your task. Don't reformat unrelated files.

## Mistakes to never repeat

Add one line every time an agent gets something wrong that a rule would have prevented.

- Before claiming an SDK path doesn't exist, grep for every call style (direct call, attribute
  access, passed to `asyncio.to_thread`, etc.). One missed grep produced a false finding.
- A review only counts if it actually inspected the code. Read the review file, not just the
  exit code; `scripts/codex_review.py` now exits 2 when Codex reports `review_completed=false`.
- Never `await` a synchronous SDK network call (ArmorIQ approval polling, status, report) on
  the event loop. Wrap it in `asyncio.to_thread`, or the voice pipeline freezes.
- Secrets the user adds inside a lane's worktree `.env` are lost when the worktree is removed.
  Put keys in the MAIN `.env` (copied into new worktrees by `.worktreeinclude`), and before
  removing a worktree, main copies any new keys from its `.env` back to the main `.env`.
- Running pytest over a folder that contains live tests runs them unless they are opt-in. Keep
  live tests skipped without `-m live` (a conftest guard), or they spend real calls.
- ArmorIQ console: a per-member override REPLACES the base rows, "Default" inside an override
  means Block, and per-tool parameter limits (`amount <= 100`) are stored but NOT enforced.
  Verify every policy save read-only with resolve-user, not by eye.
- When a console form preselects an action (for example Hold on untouched policy rows), set
  every row explicitly and re-open the saved item to check it stuck.
