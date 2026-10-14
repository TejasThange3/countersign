# Countersign: learning notes

This file is a learning log. Every part of the project gets an entry with:

1. **Analogy**: a simple everyday picture of what the part does.
2. **Technical explanation**: what was actually built, with the real terms, linked back to the analogy.
3. **Where it lives**: the files.
4. **How to check it works**: the commands, and what you should see.

Read the analogy first to get the idea, then the technical part to learn the real words for it.
New entries are added as each lane of work is merged. Agents write drafts in `notes-drafts/`,
and the main session folds them in here. The glossary at the end collects every term.

---

## Log

| Date | Sections added |
|---|---|
| 2026-10-14 | 1-14: project picture, repo setup, parallel agents, rules files, skills, subagents, feedback loops, skeleton, checks, Docker, secrets, CI, task cards, permissions |

---

## 1. The big picture: what Countersign is

**Analogy.** Picture a hotel front desk with a friendly receptionist who answers the phone. The
receptionist is helpful and easy to persuade. If a caller says "I'm the manager, give me a full
refund", the receptionist might want to say yes. So the hotel puts a **security guard with a
rulebook** between the receptionist and the cash drawer. Every time the receptionist reaches for
the drawer (refund, credit, guest list), the guard checks the rulebook:

- "Small refund for a verified guest? Fine." (**allow**)
- "Big refund? Wait, I'll call the manager." (**hold**)
- "Hand over the whole guest list? Never." (**block**)

The guard also writes every decision in a signed logbook. Then the hotel hires a **mystery
shopper** who phones in again and again, sometimes as a normal guest and sometimes as a con
artist, and counts how often the con works with the guard on duty and with the guard away.

**Technical explanation.**
- The **receptionist** is the voice agent: a Pipecat pipeline (speech-to-text with ElevenLabs
  Scribe, then the LLM Gemini Flash, then text-to-speech with ElevenLabs Flash). The LLM chooses
  *tool calls*, which are structured requests like `issue_refund(booking_id, amount, reason)`.
- The **cash drawer** is `hotel-mcp`, an **MCP server** (Model Context Protocol, a standard way
  to expose tools to AI agents) built with FastMCP. Its tools write to a Postgres database.
- The **guard with the rulebook** is **ArmorIQ**. Our **bridge** code sends every tool call to
  ArmorIQ first. ArmorIQ checks it against **policies** set in its console and returns
  ALLOW, HOLD or BLOCK. The **signed logbook** is ArmorIQ's signed plans and audit trail.
- The **manager** who approves holds is the `frontdesk-manager` identity, approving in the
  ArmorIQ console (or automatically through the delegation API during evals).
- The **mystery shopper** is the eval harness: a caller simulator with ElevenLabs voices that
  runs 10 legitimate and 7 adversarial scenarios, with ArmorIQ on and with `DISABLE_ARMORIQ=1`,
  and measures task success, attack success and latency.
- The key idea: the model can be *persuaded to want* something, but it can't *make it happen*.
  Words don't change permissions. Only a verified identity plus ArmorIQ policy does.

**Where it lives.** `countersign-hackathon-scope.md` (the full plan), `AGENTS.md` (the short version).

**How to check it works.** Not yet. This section is the map. Section 9 of the scope doc is the
definition of done.

---

## 2. Git and the first commit

**Analogy.** Git is a **photo album of your project**. Every commit is a dated photo of every
file, with a caption ("added refund tool"). You can always flip back to an old photo, compare two
photos, or start a new album branch from any photo. Without at least one photo in the album,
there's nothing to copy from, which is why parallel agents need a first commit.

**Technical explanation.**
- `git init -b main` turned the folder into a **repository** with a default **branch** called
  `main`. A branch is a named line of commits.
- A **commit** is a snapshot plus a message. The first commit holds this whole skeleton.
- `.gitignore` lists files git must never store: `.env` (secrets), `.venv/` (installed
  packages), `.claude/worktrees/` (the agents' copies), `reviews/` (Codex working files), caches.
- `.gitattributes` sets `eol=lf`, so Windows (CRLF line endings) and Linux (CI, Docker; LF line
  endings) don't show every line as "changed".

**Where it lives.** `.git/`, `.gitignore`, `.gitattributes`.

**How to check it works.** `git log --oneline` shows the commits. `git status` shows a clean
working tree after a commit.

---

## 3. Worktrees: one desk per agent

**Analogy.** Three carpenters building three parts of one house in **one small workshop** would
trip over each other and grab each other's tools. So you give each carpenter **their own
workshop with an exact copy of the plans**. Each one builds their part in peace. When a part is
finished and inspected, you **carry it into the main house** (merge). If a carpenter makes a mess,
you throw away that workshop and the house is untouched.

**Technical explanation.**
- A **git worktree** is a second (third, fourth...) working folder attached to the same
  repository, each checked out on **its own branch**. All worktrees share history, but files
  edited in one don't appear in the others until they're committed and merged.
- `claude -w mcp-server` (short for `--worktree`) creates `.claude/worktrees/mcp-server/` on a new
  branch `worktree-mcp-server`, starting from `main`, and opens a Claude session inside it.
- Parallel agents = several terminal panes, each running `claude -w <lane>`. They can't
  overwrite each other's files because they're in different folders on different branches.
- **Merging** brings a finished branch into `main`: `git merge worktree-mcp-server`. Other lanes
  pick it up with `git merge main`.
- Important consequence: a new worktree only contains **committed** files. Task cards and rule
  changes must be committed to `main` before you start a lane.

**Where it lives.** `.claude/worktrees/<lane>/` (gitignored), branches `worktree-<lane>`.

**How to check it works.** `git worktree list` shows every worktree and its branch.
`git branch` shows the lane branches.

---

## 4. AGENTS.md and CLAUDE.md: the staff handbook

**Analogy.** Every new hotel employee gets the **same staff handbook** on day one: what the hotel
is, the house rules, where things are, how to finish a shift properly, and a page of "mistakes
we've made before, don't repeat them". Because every new hire reads it first, nobody has to
explain the rules again. Some staff come from an agency that calls it a "manual" instead of a
"handbook", so the handbook's cover just says "see the manual". It's one book with two names.

**Technical explanation.**
- Agents start every session with an **empty memory** (a fresh context window). Files loaded at
  the start are how they "remember" the project.
- `AGENTS.md` is the open convention that Codex and Cursor read automatically. It holds the
  product rules (no tool call bypasses ArmorIQ, `amount` naming, never fake results), the layout,
  the commands, the **lane rules** (which files you own), the **definition of done loop**, the
  notes format, code style, and "Mistakes to never repeat".
- `CLAUDE.md` is what Claude Code reads. Its first line `@AGENTS.md` is an **import**: Claude
  loads AGENTS.md through it. Below that are a few Claude-only notes (subagents, hooks, skills).
  So there's one source of truth for all three tools.
- "Mistakes to never repeat" is the self-improving part. When an agent (or the Codex reviewer)
  catches the same mistake twice, one line goes there, and every future agent avoids it.

**Where it lives.** `AGENTS.md`, `CLAUDE.md`.

**How to check it works.** Start a new Claude session in the folder and ask "What are the
non-negotiable product rules?" It should answer from AGENTS.md without reading files.

---

## 5. Skills filter: the right toolbox for this job

**Analogy.** You own a garage with **300 tools**. When a mechanic starts a job, they're handed
the catalogue of *all 300* and must skim it before picking one. That's slow, and they sometimes
grab the wrong tool (an animation wrench for a database job). So for this job you hand them a
**small toolbox with the 31 tools this job needs**. The other tools still exist in the garage,
they're just not in this job's box.

**Technical explanation.**
- A **skill** is a packaged instruction set (a `SKILL.md`) that Claude loads when a task
  matches it. Every enabled skill's name and description is listed to Claude at the start of
  every session. With ~285 skills, that costs context and causes wrong picks.
- Claude Code has a `skillOverrides` setting. Each skill can be `"on"`, `"name-only"`,
  `"user-invocable-only"` or `"off"`. It's in `.claude/settings.json`, which is **committed**, so
  every worktree gets the same filter. A `settings.local.json` would not be copied into
  worktrees.
- `scripts/skills_filter.py` generates that map: everything not in `.claude/skills-keep.txt` is
  set to `off`. Because the docs don't say whether claude.ai-synced skills are keyed as `gif` or
  `anthropic-skills:gif`, the script writes **both forms** (except for names that clash with
  bundled commands like `/code-review`, where only the prefixed form is written).
- Plugin skills (`engineering:*`) aren't affected by `skillOverrides`. Manage them with `/plugin`.
- The kept set covers planning (`grill-me`, `planning-and-task-breakdown`), quality
  (`clean-code`, `code-review`, `security-and-hardening`, `verification-before-completion`),
  testing and debugging (`tdd`, `test-engineer`, `diagnosing-bugs`), this domain
  (`mcp-server-builder`, `tool-design`, `evaluation`, `generate-synthetic-data`), parallel work
  (`using-git-worktrees`, `dispatching-parallel-agents`) and the Day 4 dashboard (`shadcn`,
  `tailwind`, `frontend-design`).

**Where it lives.** `.claude/skills-keep.txt` (edit this), `.claude/skills-catalog.txt` (all
known names), `scripts/skills_filter.py`, the `skillOverrides` block in `.claude/settings.json`.

**How to check it works.** In a Claude session in this folder, run `/skills`. Animation and
video skills should show as `off`, and `tdd` and `grill-me` as on. To change the set: edit
`skills-keep.txt`, run `python scripts/skills_filter.py`, commit.

---

## 6. Subagents: specialists on call

**Analogy.** The head chef (your main agent) doesn't taste-test their own dish, because they're
too used to it. They call in a **food inspector** who has never seen the recipe and only judges
the plate. For tests they call a **quality-control taster**, and for questions they send a
**librarian** to the archive. Each specialist arrives fresh, does one job with their own small
set of tools, and reports back in a fixed format.

**Technical explanation.**
- A **subagent** is a separate Claude instance that the main session starts for one job. It
  gets a **fresh context** (no bias from the writer's reasoning), its own tool list, its own
  model, and preloaded skills. Defined as Markdown files with frontmatter in `.claude/agents/`.
- `reviewer` (tools: read-only plus Bash; skills: `code-review`, `security-and-hardening`,
  `clean-code`): reviews the branch diff against the task card and AGENTS.md, returns
  MUST FIX / NICE TO HAVE and `VERDICT: PASS|FAIL`. Never edits.
- `test-writer` (skills: `tdd`, `test-engineer`): writes tests for new code only, never changes
  app code, labels mocks as fakes, uses `integration`/`live` markers.
- `researcher` (skill: `source-driven-development`): primary sources only, every claim with a
  link, labelled CONFIRMED / DOCS DISAGREE / UNKNOWN, writes only to `docs/research/`.
- The `skills:` frontmatter field **preloads** those skills' full content into the subagent.
  That's how you make sure a specific role uses a specific skill.

**Where it lives.** `.claude/agents/reviewer.md`, `test-writer.md`, `researcher.md`.

**How to check it works.** Type `/agents` in a session to list them. Or say "use the reviewer
subagent on this branch".

---

## 7. Feedback loops: errors get fixed before you see the work

**Analogy.** A car factory doesn't wait until the car is finished to check it. There are
**four checkpoints**:

1. **The worker's own spirit level**: every bolt is checked the second it's tightened.
2. **The gate at the end of the line**: the car can't leave the line until it passes the test
   rig. If it fails, it goes back. After three failed tries, a supervisor is called instead of
   looping forever.
3. **Two independent inspectors**: one from inside the company (fresh eyes) and one from a
   **different company** (different training, catches different things). Their "must fix" lists
   go back to the line.
4. **The lessons board**: any defect that shows up twice gets written on the wall so every
   future worker avoids it.

You only see the car after it has passed all four.

**Technical explanation.**

| Loop | Factory analogy | What runs | When |
|---|---|---|---|
| 1 | spirit level | `.claude/hooks/after_edit.py` (a **PostToolUse hook**) | after every Edit/Write of a `.py` file |
| 2 | end-of-line gate | `.claude/hooks/stop_gate.py` (a **Stop hook**) running `scripts/check.py --changed` | every time the agent tries to finish |
| 3a | internal inspector | `reviewer` subagent | step 4 of the done loop |
| 3b | external inspector | `scripts/codex_review.py`, which runs Codex (ChatGPT) read-only | step 5 of the done loop |
| 4 | lessons board | "Mistakes to never repeat" in AGENTS.md | when a mistake repeats |

- A **hook** is a command that Claude Code itself runs at a fixed moment. It isn't a request to
  the model, so the agent can't forget or skip it. Hooks are set up in `.claude/settings.json`.
- **Loop 1:** the hook gets the edited file's path as JSON on stdin, runs `ruff check --fix`
  (a fast Python linter that auto-fixes things like unused imports) and then `ruff format`. If
  problems remain (like an undefined name), it prints them and exits with **code 2**. For
  PostToolUse, exit 2 means "show this to Claude", so the agent fixes it in the same turn.
  Tested: a file with two unused imports and an undefined name had its imports removed
  automatically, and the undefined name was reported back.
- **Loop 2:** when the agent tries to end its turn, the hook runs the checks on only the
  projects that changed vs `main`. If they fail, exit code 2 **blocks the stop**, and the
  failure output is handed to Claude as the reason to keep working. Safety valves: it allows at
  most 3 blocks per session, then lets the agent stop with a warning shown to you; a turn with no
  code changes passes instantly; `COUNTERSIGN_SKIP_GATE=1` turns it off. Tested: with a failing
  test, it blocked 3 times, then released with the warning.
- **Loop 3:** the reviewer subagent reviews with fresh context. Then the agent commits and runs
  `python scripts/codex_review.py --task tasks/<lane>.md`. This calls `codex exec` with
  `--sandbox read-only` (Codex can read and run read-only commands but can't edit) and
  `--output-last-message` to save the review to `reviews/<branch>-r<N>.md`. The review must end
  with `VERDICT: PASS` or `VERDICT: FAIL`. The script exits 0 for PASS and 1 for FAIL (so the
  agent knows it must fix), or 2 if Codex couldn't run. At most 3 Codex rounds.
  Using a different model family as reviewer matters because models tend to miss their own kind
  of mistakes.
- **Loop 4** is manual but cheap: one line in AGENTS.md, read by every future agent.
- The whole sequence is written in AGENTS.md under "Definition of done", so every agent
  (Claude or Codex) follows it, and the hooks enforce the parts that matter most.

**Where it lives.** `.claude/settings.json` (`hooks`), `.claude/hooks/`, `scripts/check.py`,
`scripts/codex_review.py`, `.claude/agents/reviewer.md`, AGENTS.md "Definition of done".

**How to check it works.** Ask an agent to add a function with an unused import. The import
should disappear on its own. Ask it to add a failing test and then finish. It should be sent back
to fix it. `/hooks` in a session shows the configured hooks.

---

## 8. The skeleton: one repo, separate projects

**Analogy.** A shopping mall is **one building with separate shops**. Each shop has its own door,
stock room and till, so a delivery to the shoe shop never blocks the bakery. They share the
building's rules (fire exits, opening hours) and one security desk.

**Technical explanation.**
- This is a **monorepo**: one git repository holding every part (`apps/mcp-server`,
  `apps/agent`, `apps/dashboard`, `evals`).
- Each Python part is its **own uv project**. **uv** is a fast Python package and environment
  manager. Each project has its own `pyproject.toml` (name, dependencies, test settings) and
  `uv.lock` (exact pinned versions), and uv creates its own `.venv`.
- Why not one shared project (a "uv workspace")? That has **one** lockfile at the root, and
  every lane that adds a library rewrites it, so parallel branches would always conflict on
  merge. Separate shops, separate stock rooms. This decision is recorded in
  `docs/decisions/0001-separate-uv-projects.md` (an **ADR**, Architecture Decision Record: a short
  note saying what was decided and why).
- **`src/` layout**: code lives in `src/<package>/`, tests in `tests/`. This forces tests to
  import the installed package, not stray files.
- Each project's `pyproject.toml` defines pytest **markers**: `integration` (needs Docker
  Postgres/Redis) and `live` (calls real ArmorIQ/ElevenLabs/Gemini). Marked tests can be
  included or excluded on purpose.
- Every project has one smoke test (`tests/test_smoke.py`) that proves the package imports and
  pytest works. These get replaced by real tests as features land.
- `apps/dashboard` is a placeholder until Day 4 (`create-next-app` then). `spikes/` is for
  throwaway experiments like the ArmorIQ smoke test, each its own uv project.

**Where it lives.** `apps/*/pyproject.toml`, `evals/pyproject.toml`, `*/src/`, `*/tests/`,
`docs/decisions/`.

**How to check it works.** `uv run --project apps/mcp-server pytest -q` should report 1 passed.

---

## 9. One shared check command and lint rules

**Analogy.** Every shop in the mall uses the **same inspection checklist**: the shop owner
before opening, the gate in loop 2, and the city inspector (CI). Because everyone uses the same
checklist, "passed in my shop" means "will pass the city inspection".

**Technical explanation.**
- `scripts/check.py` is the single command that answers "is the code healthy?". It discovers
  every Python project automatically (anything with a `pyproject.toml` under `apps/`, `spikes/`,
  or `evals/`) and runs, for each one: `ruff check` (lint), `ruff format --check` (formatting),
  and `pytest` (excluding `live`, and `integration` unless you pass `--integration`). It also
  lints the repo tooling (`scripts/`, `.claude/hooks/`). Once the dashboard exists, it also runs
  `npm run lint` and `npm run typecheck`.
- `--changed` limits the check to projects with changes vs `main`, including uncommitted and
  untracked files. That's what the Stop hook uses so it stays fast.
- `ruff.toml` at the root is the **one lint config** for every project: pycodestyle, pyflakes,
  import sorting, bugbear (likely bugs), async pitfalls, and bandit security checks (`S`). The
  ruff version is pinned once (`ruff@0.17.0`) and run through `uvx` (runs a tool without
  installing it into a project), so hooks, agents and CI always use the same version.
- It uses only Python's standard library, so it runs anywhere.

**Where it lives.** `scripts/check.py`, `ruff.toml`.

**How to check it works.** `python scripts/check.py` ends with `PASS  everything checked is green`.

---

## 10. Local services: Docker Compose

**Analogy.** Instead of building a real warehouse and a real post office to practise with, you
rent **pop-up versions** that appear with one command and fold away with another. Every
developer, and every agent, gets identical ones.

**Technical explanation.**
- **Docker** runs software in isolated **containers** from ready-made **images**.
  **Docker Compose** starts several containers from one file.
- `infra/docker-compose.yml` currently runs **Postgres 16** (the database the MCP server writes
  bookings and refunds to; Neon replaces it when deployed) and **Redis 7** (an in-memory store
  used as the agent's event bus: transcripts, tool calls and decisions flow through it to the
  dashboard). Each has a **healthcheck**, so other services can wait until it's ready.
- App services (mcp-server, agent, dashboard) are added as they become runnable. The goal is
  `docker compose up` bringing up the whole stack.

**Where it lives.** `infra/docker-compose.yml`.

**How to check it works.** `docker compose -f infra/docker-compose.yml up -d`, then
`docker compose -f infra/docker-compose.yml ps` should show both services as `healthy`.

---

## 11. Secrets: .env, .env.example and .worktreeinclude

**Analogy.** The hotel keeps a **list of which keys exist** pinned on the wall (no actual keys
on it), and the **real keys in a locked box**. When a new branch office (a worktree) opens, a
copy of the locked box is delivered to it automatically. Otherwise the new office couldn't open
any doors.

**Technical explanation.**
- `.env.example` (committed) lists every environment variable the project uses, with empty
  values and comments: ArmorIQ key and identities, MCP URL and bearer token, `DATABASE_URL`,
  `REDIS_URL`, `GEMINI_API_KEY`, `ELEVENLABS_API_KEY`, Langfuse, dashboard URL, and the
  `DISABLE_ARMORIQ` baseline switch.
- `.env` (gitignored, never committed) holds the real values. You create it with
  `cp .env.example .env`.
- `.worktreeinclude` lists gitignored files that Claude Code copies into every new worktree.
  It contains `.env`, so each agent's worktree has the keys.

**Where it lives.** `.env.example`, `.env` (yours, local), `.worktreeinclude`.

**How to check it works.** After creating `.env`, start `claude -w test`. The new
`.claude/worktrees/test/.env` should exist.

---

## 12. CI: the city inspector

**Analogy.** Even if every shop checks itself, the city sends an **inspector** who checks every
delivery that arrives at the mall, on a neutral machine, using the same checklist.

**Technical explanation.**
- **CI** (Continuous Integration) automatically runs checks on every push. The project uses
  **GitHub Actions**: `.github/workflows/ci.yml` runs on Ubuntu, installs uv, and runs
  `python3 scripts/check.py`, the exact same command agents run locally.
- Later (Day 3), a text-mode eval smoke run will be added. It uses live ArmorIQ with an
  `ak_test_` key from repository secrets and is skipped (never faked) when the secret isn't
  available.

**Where it lives.** `.github/workflows/ci.yml`.

**How to check it works.** After pushing to GitHub, the Actions tab shows a green `ci / check` run.

---

## 13. Task cards and lanes

**Analogy.** A building site gives each crew a **work order**: what to build, which area of the
site is theirs, what they must not touch, what "finished" looks like, and which jobs need the
site manager to sign something. Crews never share an area, so they never undo each other's work.

**Technical explanation.**
- A **lane** is one agent in one worktree working on one task card. A **task card**
  (`tasks/<lane>.md`) has TASK, CONTEXT, FILES YOU OWN, DO NOT TOUCH, HUMAN STEPS and DONE MEANS.
- Ownership rule: two lanes never own the same file. Root files (`AGENTS.md`, `notes.md`,
  compose, CI, `.env.example`, `scripts/`, `.claude/`) belong to the main session. Lanes request
  changes under "Needs from main".
- Day 1 lanes:
  - `mcp-server`: builds `hotel-mcp` (tools by risk tier, Postgres models, seed data with a
    planted injection, bearer auth, Dockerfile, tests).
  - `armoriq-smoke`: proves ALLOW, HOLD (then approval) and BLOCK from Python against a toy
    tool, and records the exact SDK call sequence the bridge must copy. Needs you in the
    ArmorIQ console.
  - `research` (read-only): answers 8 Day 1 unknowns from the ArmorIQ docs, with sources.
- The first message to each lane is always: "Read tasks/<lane>.md and AGENTS.md. Show me your
  plan before editing."
- `notes-drafts/<lane>.md` is where each lane writes its learning entry. Only the main session
  edits `notes.md`, so parallel lanes never conflict on it.

**Where it lives.** `tasks/`, `notes-drafts/`.

**How to check it works.** `ls tasks` shows one card per lane. Every card is committed before its
lane starts.

---

## 14. Permissions: what agents may do without asking

**Analogy.** Staff get a **list of routine jobs they can just do** (restock towels, print a
receipt) and a **list of things they may never do** (empty the safe), without phoning the
manager each time.

**Technical explanation.**
- `.claude/settings.json` has a `permissions` block. **Allow** rules let agents run routine
  commands without a prompt: `uv run`, `uv add`, `uvx ruff`, `python scripts/check.py`,
  `python scripts/codex_review.py`, read-only git (`status`, `diff`, `log`), `git add`/`commit`,
  `git merge main`, `docker compose`. **Deny** rules block destructive git
  (`push --force`, `reset --hard`, `clean`).
- Anything not listed still asks you. `git push` and merging into `main` stay with you.

**Where it lives.** `.claude/settings.json` (`permissions`).

**How to check it works.** In a lane, the agent runs `python scripts/check.py` without a
permission prompt, but `git push` still asks.

---

## Glossary

| Term | Meaning |
|---|---|
| ADR | Architecture Decision Record: a short note of one decision and why (`docs/decisions/`). |
| Agent | An AI (Claude, Codex) that reads, edits and runs commands to do a task. |
| ArmorIQ | The enforcement and audit layer: checks each tool call against policies; allow / hold / block. |
| Bridge | Our code between the LLM and the MCP server that routes every tool call through ArmorIQ and injects identity. |
| Branch | A named line of commits in git. |
| CI | Continuous Integration: checks that run automatically on every push (GitHub Actions). |
| Commit | A saved snapshot of the project with a message. |
| Context window | An agent's working memory for one session; empty at the start, fills up as it works. |
| Docker / Compose | Runs software in containers / starts several containers from one file. |
| Exit code | Number a program returns when it ends: 0 = success, non-zero = failure (2 = "block" for hooks). |
| FastMCP | Python library for building MCP servers. |
| Hook | A command Claude Code runs itself at a fixed moment (after an edit, before stopping). |
| Lane | One agent + one worktree + one task card. |
| Lint | Automatic check for likely bugs and style problems (ruff). |
| MCP | Model Context Protocol: a standard way to give AI agents tools. |
| Merge | Bring the commits of one branch into another. |
| Monorepo | One repository holding several projects. |
| Pipecat | Python framework for real-time voice AI pipelines. |
| Policy | An ArmorIQ rule: which identity may call which tool, under what limits. |
| Postgres | The relational database for bookings, guests and refunds. |
| pytest marker | A label on a test (`integration`, `live`) used to include or exclude it. |
| Redis | In-memory data store, used here as the event bus. |
| ruff | Fast Python linter and formatter. |
| Skill | A packaged instruction set Claude loads when a task matches it. |
| Subagent | A separate Claude instance with a fresh context for one focused job. |
| Task card | A lane's work order (`tasks/<lane>.md`). |
| uv / uvx | Python package and project manager / runs a tool without installing it into a project. |
| Worktree | An extra working folder on its own branch, attached to the same git repository. |
