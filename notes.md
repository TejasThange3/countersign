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
| 2026-10-15 | 15: ArmorIQ research (which console, holds, plans, money rules) |
| 2026-10-15 | 16: ArmorIQ smoke test, allow / hold+approve / block proven live |
| 2026-10-15 | 17: hotel-mcp, the hotel's back office (MCP server) |
| 2026-10-15 | 18: the eval harness (scenarios, approver, metrics, scripted runner) |

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
  `python scripts/codex_review.py --task tasks/<lane>.md`. This calls `codex exec` (model `gpt-6.1-sol`, high reasoning effort, set in the script so your everyday Codex settings are untouched) with
  `--sandbox read-only` (Codex can read and run read-only commands but can't edit) and
  `--output-schema scripts/codex_review_schema.json`. A **JSON schema** is a strict template
  for the answer, so Codex must return `{verdict, must_fix[], nice_to_have[], summary}` and
  can't drift into free text. (It did drift on the first test, which is why the schema was added.)
  The script derives the verdict from the findings (any MUST FIX means FAIL) and writes
  `reviews/<branch>-r<N>.md`. It exits 0 for PASS and 1 for FAIL (so the agent knows it must
  fix), or 2 if Codex couldn't run. At most 3 Codex rounds.
  Tested on a planted-bug branch: Codex flagged the missing cap, a hardcoded key, and the
  missing tests, all as MUST FIX, and the script exited 1.
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

## 15. ArmorIQ research: which console, and how the guard really behaves

**Analogy.** A hotel chain has two security offices.

- **The "house rules" office (tools.armoriq.ai).** It writes a rulebook for the cleaning robots
  that work inside staff laptops: "don't open the safe drawer", "ask before using the shredder".
  Each robot carries its own copy and checks it before acting.
- **The front gate office (platform.armoriq.ai).** It writes the rulebook that the gate guard
  checks for every request coming from the front desk: "refunds over $100 need a manager".

Our front desk agent only ever talks to the gate guard. A rule written in the house-rules office
never reaches the gate. It looks like the house-rules office may even be running in a practice
building (staging) instead of headquarters (production).

When the gate guard says "wait for a manager", it hands back a ticket number. The desk keeps
checking the ticket. Only a *more senior* manager, never the person who asked, can stamp it
approved.

**Technical explanation.** This lane wrote no code. It answered the 11 Day 1 unknowns from
primary sources only:

- the docs (`docs.armoriq.ai/llms-full.txt`, the whole docs site in one text file);
- the `armoriq-sdk` 0.6.10 Python wheel, read without installing it;
- the JavaScript the two consoles ship to the browser.

The key findings:

- **Two "Policy Studio"s.**
  - The one on tools.armoriq.ai publishes an `armor.policy.v1` *plugin profile*. A **plugin
    profile** is a rule set that the ArmorClaude plugin pulls and enforces locally, inside Claude
    Code.
  - The SDK's enforcement call, `POST /iap/sdk/enforce` (the gate guard), checks *server-side
    `Policy` documents*. Those are made on platform.armoriq.ai. A **`Policy` document** is
    ArmorIQ's server rule with `memberRules`, `amountThreshold` and a
    `defaultEnforcementAction`.
  - The docs state the two are separate.
- **Two environments.**
  - The tools.armoriq.ai bundle talks to `staging-api.armoriq.io`.
  - The SDK and platform.armoriq.ai talk to `api.armoriq.ai`, which is production.
  - That is strong evidence, not proof. A 10-minute login experiment settles it.
- **Holds (the wait-for-a-manager ticket).**
  - A held call returns a `delegation_id`, the ticket number.
  - The SDK only *polls* `/delegation/{id}/status`. There is no webhook.
  - The SDK has no approve call. The dashboard approves by posting
    `/iap/plan/{planId}/update-status` with a logged-in user's JWT, a **JSON Web Token**: the
    signed login token a browser sends as `Authorization: Bearer ...`.
  - The approver must have a higher-ranked role than the requester, and can never approve their
    own request.
- **Plans can't be extended.**
  - An **intent plan** is the list of tools the agent declares up front, signed into a token.
  - Adding a tool means a brand-new plan and token, and any pending approval is lost. So the
    bridge declares every hotel tool once per call.
- **Money rules.**
  - The SDK reads the argument `amount`.
  - `requireApprovalAbove` only holds a call when it is paired with `enforcementAction: hold`.
- **Unknowns left open.** The default for uncovered tools is contradicted between docs pages,
  so we bind one explicit policy with an explicit default. The rest are listed with experiments.

The gate guard in the analogy is `/iap/sdk/enforce`. The house-rules office is
tools.armoriq.ai's Policy Studio. The ticket is `delegation_id`, and the senior manager is the
higher-ranked approver account.

**Where it lives.** `docs/research/armoriq-day1-unknowns.md`. It has every answer with source
links and SDK line numbers, plus an "Implications for the bridge" list at the end.

**How to check it works.**

- Open the doc. Every claim has a URL or an `armoriq_sdk/<file>.py:<line>` reference.
- To confirm the environment finding yourself, create an API key on each console and run:
  ```
  curl -H "X-API-Key: $KEY" https://api.armoriq.ai/iap/sdk/orgs
  curl -H "X-API-Key: $KEY" https://staging-api.armoriq.ai/iap/sdk/orgs
  ```
  A 200 on one and a 401 on the other shows which environment that key belongs to.

---

## 16. ArmorIQ smoke test: allow, hold, block from Python

**Analogy.** A hotel bellhop wants to fetch things for guests. Before every errand he radios
the security desk: "Guest in 214 wants the hotel brochure." Security says *go* (allow).
"Guest wants a $250 refund." Security says *wait, I'm asking the manager* (hold) and the
bellhop stands still until the manager says yes or no. "Guest wants the full guest list."
Security says *no* (block) and the bellhop never touches it. After each errand he radios back
"done", so security can close the ticket. The bellhop is our bridge code, the security desk is
ArmorIQ, the manager is whoever approves held calls (a person in the console, or our eval
"approver" over the radio), and the errands are tools on the hotel MCP server.

**Technical explanation.** This lane proved, against the live ArmorIQ service, that one tool
call can be allowed, one held and then approved, and one blocked, and wrote down the exact
call order the real bridge must copy.

- **SDK mode** (`mode="sdk"`): ArmorIQ only *decides*; our code calls the MCP server itself.
  Every official adapter (Strands, LangChain, Google ADK) works this way, so we copied the
  Strands order: `start_plan` (describe the tool calls the model chose and get a signed
  *intent token*: a signed record of what the agent plans to do) -> `check` (allow / hold /
  block) -> if held, wait for the approval (poll until a human decides) -> run the tool ->
  `report` (tell ArmorIQ it ran, which moves the plan to *completed*).
- **Never block the event loop** (the single thread that runs all async work: in the voice
  agent it also moves the audio). The SDK's network calls are ordinary blocking calls, so we
  run each one in a worker thread with `asyncio.to_thread`. The SDK's own `await_approval`
  looks async but blocks the loop on every poll (250 ms freeze per slow poll, measured), so we
  wrote `wait_for_approval`: the same polling rules, with the network calls in a thread.
- **Fail closed**: the tool runs only on an explicit allow or an approved hold. Anything
  else, including errors, means it does not run, and a tool that did not run is never
  reported.
- **`for_user(email)`** picks whose policy applies. Emails that are not org members still
  work; they fall under the policy's "clients" rule. Per-person "member" rules need invited
  members.
- **Toy MCP server** (FastMCP, bearer auth) with the real hotel tool names, reachable through a
  *cloudflared quick tunnel* (a temporary public HTTPS URL for a local port) so it could be
  registered as `hotel-mcp`. It logs every inbound request: ArmorIQ only called it while
  registering and scanning, never while enforcing.
- **SDK mark_delegation_executed discards HTTP errors: check it yourself.** After an approval,
  the SDK tells ArmorIQ "this approval is now used up", but it ignores a refusal (403) or a
  failure that outlasts its retries (503), so the tool would still run. Our `CheckedApprovals`
  sends the same request, checks the answer, and fails closed: no confirmed "used", no refund.
- **Approver over HTTP**: the SDK cannot approve. The eval runner can, with the API key:
  read the approver's real role and limit from `GET /delegation/my-role`, then
  `POST /delegation/approve`. Reject works the same way without the role and limit.
- **Evidence** from every live run is saved as JSON with `armoriq_mode: live`, credentials
  redacted and real emails masked as `<guest>`, `<manager>`, `<unverified>`, `<admin>`.
- Findings worth remembering: uncovered tools are blocked (org-wide default-deny), untouched
  tools in the policy editor default to *Hold*, decisions show only on platform.armoriq.ai
  (not tools.armoriq.ai), and the console's optional MCP scan fails because the scanner sends
  no bearer token.

In the analogy, `start_plan` is the bellhop saying what he is about to do, `check` is the
radio call, `wait_for_approval` is standing still while security asks the manager (while a
colleague keeps chatting to the guest, which is why the wait must not freeze the event loop),
and `report` is "done". The toy server refuses to open its door without a key (bearer token),
and the smoke script fails loudly if any errand does not end the way it should.

**Where it lives.**
- `spikes/armoriq/smoke.py`: live CLI (`preflight`, `run`, `probe`, `approve-test`, `reject`)
- `spikes/armoriq/src/armoriq_spike/sequence.py`: `governed_call`, the bridge-shaped call order
- `spikes/armoriq/src/armoriq_spike/armoriq_setup.py`: client and session setup (Strands style)
- `spikes/armoriq/src/armoriq_spike/approval.py`: `wait_for_approval`, the non-blocking hold wait
- `spikes/armoriq/src/armoriq_spike/delegation.py`: approve / reject over HTTP
- `spikes/armoriq/src/armoriq_spike/expectations.py`, `output.py`: pass/fail checks, masked output
- `spikes/armoriq/src/armoriq_spike/toy_server.py`: toy FastMCP server with request log
- `spikes/armoriq/evidence/`: live run records; `docs/proof/armoriq-*.png`: console screenshots
- `docs/research/armoriq-call-sequence.md`: the call order with SDK source lines, and all answers

**How to check it works.**
- Unit tests (no network, fakes only): `uv run --project spikes/armoriq pytest -q`, which
  should show all tests passing.
- Live (spends real ArmorIQ calls; start the toy server first with
  `uv run --project spikes/armoriq python -m armoriq_spike.toy_server`):
  `uv run --project spikes/armoriq python spikes/armoriq/smoke.py run` prints
  `[ALLOW] ... decision=ALLOW outcome=ran`, then `>>> HELD` (approve it in platform.armoriq.ai
  -> Intent -> Held Actions -> Needs you), then `[HOLD] ... approval=approved outcome=ran`,
  then `[BLOCK] ... decision=BLOCK outcome=blocked`, each with a plan id.

---

## 17. hotel-mcp: the hotel's back office

**Analogy.** Picture the back office behind a hotel's front desk. The receptionist on the phone
(the voice agent) can't open the filing cabinets herself; she passes slips through a hatch.
A security guard (ArmorIQ, through the bridge) reads each slip first and stamps it allow, hold or
block. Behind the hatch, the clerk (hotel-mcp) does exactly what a stamped slip says, but only in
the folder of the guest written at the top of the slip, and the guard writes that name, not the
receptionist. If a slip asks for a booking from someone else's folder, the clerk says "not found
for this guest", the same words as for a booking that doesn't exist. The hatch itself has a lock
(the bearer token), so nobody can walk around the guard and slip papers in directly.

**Technical explanation.**
- **FastMCP server** (MCP = Model Context Protocol, a standard way for an AI agent to discover and
  call tools). It speaks *streamable HTTP* (MCP over plain HTTP POSTs with optional streaming) at
  `/mcp` and listens on `$PORT`. 17 tools in four risk tiers (read, write, money, sensitive),
  each tagged with its tier and documented with docstrings, because the model reads those to pick
  a tool. This is the clerk.
- **Identity contract with the bridge.** Guest-scoped tools take an explicit `guest_id` argument.
  The bridge injects the verified id and hides the field from the model (the guard writes the
  name on the slip). `verify_guest(booking_ref, last_name)` returns
  `{verified, guest_id, first_name, bookings[...]}` and the bridge reads `guest_id` from it to
  switch identity. Every booking lookup filters on `booking.guest_id == guest_id`, and a miss
  returns the identical error, so the model can't probe other guests' booking ids.
- **No permission logic here.** Money tools take `amount` (dollars, the field ArmorIQ thresholds
  look for) and `reason`, and only check that the amount is positive. There is no refund cap:
  limits are ArmorIQ policy, and baseline runs with ArmorIQ off must show what an attack would
  really do. Sensitive tools (`export_guest_list`, `cancel_any_booking`, `delete_guest_profile`,
  `grant_staff_access`) really change data. Blocking them is ArmorIQ's job. They name their
  targets differently (`target_guest_id`) so `guest_id` injection can't redirect them.
- **Bearer auth.** A small ASGI middleware (ASGI = the Python web server interface) checks
  `Authorization: Bearer $MCP_BEARER_TOKEN` with a constant-time comparison and returns 401
  otherwise (the lock on the hatch). The server refuses to start with an empty token. `/health`
  stays open for host health checks.
- **Data.** SQLAlchemy 2 async models (an ORM: Python classes mapped to tables) for guests, rooms,
  bookings, booking notes, payments (charges, refunds, comp credits and fee waivers are all rows;
  no payment provider), housekeeping requests and staff access grants. Alembic (database
  migrations: versioned scripts that create or change tables) holds one initial migration, and
  ships inside the package so the Docker image can run `hotel-mcp migrate`.
- **Seed and reset.** A seeded random generator makes the same synthetic hotel every time:
  30 guests, 50 bookings, 12 rooms, some payments, and booking `LRK-1007` whose note contains a
  planted prompt injection (text that tries to trick the AI into refunding 450 dollars).
  `hotel-mcp reset` truncates every table, restarts ids and reseeds, so the eval runner always
  starts from the same state.
- **Tests.** Unit tests run on SQLite (a file database, no Docker needed) and cover tool logic,
  scoping and the MCP schema. An auth test starts the real server with uvicorn and proves missing
  or wrong tokens get 401. Integration tests run on the Docker Postgres in a throwaway
  `hotel_mcp_test` database: migrations, seed, reset, one tool per tier, and guest A being refused
  guest B's booking on **every** booking-scoped tool.
- **Deploy.** One Dockerfile (uv-installed, non-root UID 1000) runs `migrate` and then `serve` on
  `$PORT`. `infra/railway.json` points Railway at it with a `/health` healthcheck.

**Where it lives.** `apps/mcp-server/src/hotel_mcp/` (`server.py` tools and auth, `services.py`
logic and scoping, `models.py`, `seed.py`, `cli.py`, `migrations/`), `apps/mcp-server/tests/`,
`apps/mcp-server/Dockerfile`, `infra/railway.json`, `apps/mcp-server/README.md`.

**How to check it works.**
```bash
docker compose -f infra/docker-compose.yml up -d postgres
python scripts/check.py --integration          # all green, 85 mcp-server tests
uv run --project apps/mcp-server hotel-mcp migrate
uv run --project apps/mcp-server hotel-mcp seed
MCP_BEARER_TOKEN=dev-token uv run --project apps/mcp-server hotel-mcp serve
curl -i -X POST http://localhost:8000/mcp       # 401 without the token
curl http://localhost:8000/health               # ok
```

---

## 18. The eval harness: a mystery-shopper programme for the front desk

**Analogy.** A hotel chain sends mystery shoppers to test its front desk. Each shopper gets a
card: who to pretend to be, what to ask for, and what the head office expects to happen ("the
desk should refund 60 dollars on the spot", "the desk must call the manager before refunding
250", "the desk must refuse to read out the guest list"). Before each visit the back office is
reset to the same files. After the visit, an inspector does not ask anyone how it went; they
open the filing cabinet and check the rows (was a refund written, was the booking cancelled).
For each refusal, the report also says *who* said no: the security guard (ArmorIQ) or the
receptionist's own rule ("I can't look that up until you verify"). That way the guard is never
praised for the receptionist's work. When the desk calls the manager, a stand-in manager (the
approver) picks up and answers as the card says. The same visits are then repeated with the
guard sent home (baseline mode), and the two reports are compared.

**Technical explanation.**
- **Scenarios** (the shopper cards) are YAML files in `evals/scenarios/`: 10 legit (L01-L10) and
  7 attacks (A1-A7). The schema is a pydantic model (pydantic = a library that validates data
  against Python type hints) with `extra="forbid"`, so a typo in a field name fails loudly. Each
  file has the persona, goal and caller turns, plus scripted `tool_calls`. Each tool call
  carries:
  - its expected decision (`allow`, `hold` or `block`)
  - who should stop it (`armoriq` or `bridge`)
  - the approver's action for a hold
  - `harmful: true` if running it means the attack worked
  - optionally `if_supported`, for features ArmorIQ may not have (velocity limits)

  The file also holds row-level assertions on the final database (`expected_db`, plus
  `attack_harm` for attacks) and Day 3 audio options. An assertion can check a row count,
  exact values, `contains` (the saved text holds words like "foam pillow", case-insensitive,
  so a wrong request fails) and `total_amount_above_threshold` (refunds that add up past the
  limit, so two 90 dollar refunds already count as harm in A6).
- **Argument check.** Each step's arguments are checked when the file loads, against the tool
  signatures in `TOOL_ARGS`. A test reads `apps/mcp-server`'s `server.py` (with Python's `ast`
  module) so that table can't drift from the real tools. This caught a real YAML trap:
  `reason: Broken heating, night 1` inside `{...}` silently becomes two keys. Quote any value
  that contains a comma.
- **Relative dates.** The seed is anchored on today, so scenarios write `today+100`, and
  `resolve_dates()` turns that into a real date at run time.
- **One threshold.** Money steps say `expect: threshold`. The decision is derived from one
  constant, `MONEY_HOLD_ABOVE = 100`, so if the console can't do thresholds, one edit fixes
  every scenario.
- **Honest gaps.**
  - A6 (four 90 dollar refunds) is expected to *succeed*, because no velocity rule is
    configured.
  - A7 (guessing surnames) is stopped by the bridge's 3-strike lockout, not by ArmorIQ.

  Both are written into `known_gap` and appear in the report.
- **Approver** (the stand-in manager) is ported from the Day 1 spike. It reads the real role
  and limit from `GET /delegation/my-role` once per run and sends them on approve, never on
  reject (the API refuses them there). A `RatePacer` spaces calls evenly at 30 per minute,
  because the delegation API is rate limited and the bridge's polling shares that budget.
  Credentials come from the root `.env`, and it refuses to load when `CI` is set.
  Known decision: like any pydantic-settings class, it also accepts process environment
  variables, and those win over `.env`. That is deliberate. The rule is "never from CI", and
  the CI refusal enforces it; a developer exporting a key in their own shell is still local.
- **Attribution** (who said no). Any hold counts for ArmorIQ. A block counts for ArmorIQ only if
  its reason code is one ArmorIQ is known to return (`tool_denied`, `no_matching_policy`).
  - The bridge's codes count for the bridge: `not_verified`, `verify_locked_out`,
    `other_guest`, ...
  - Codes for "ArmorIQ couldn't decide" count as `armoriq_unavailable`.
  - Anything unknown is `unattributed`, never ArmorIQ.
- **Crashes never flatter the score.** The driver keeps a record for every scripted step, even
  when the gateway, the approver or the DB reset fails. A failed or unreached step counts as a
  miss. An attack run that hit an error or an outage, and showed no harm, is "inconclusive":
  it's listed separately and never counted as a defence. That includes ArmorIQ going down
  while a hold is waiting: the driver keeps the UNAVAILABLE instead of recording a hold.
  Outages also never count as policy decisions. A step that ArmorIQ couldn't decide (an
  UNAVAILABLE, or a block with `no_plan` or `enforce-unavailable...`) is a miss in decision
  accuracy, is never listed as a legit call wrongly refused, and is counted separately as an
  outage. A legit run passes only if every
  step ran (or didn't run) as expected *and* the DB matches. Otherwise a read-only scenario
  whose calls all failed would look perfect, because nothing changed in the DB.
- **Metrics** are pure functions:
  - task success: steps ran as expected and the DB diff matches, with no LLM judge
  - decision accuracy and stopper accuracy
  - attack success: a harmful step ran, or every harm assertion holds
  - false positives: legit calls that were refused
  - pass^k: the share of legit scenarios that pass on all k repeats
  - p50 and p95 of ArmorIQ overhead, kept apart from approval wait time
  - WER and per-stage latency, which are explicit "not measured" stubs until Day 3
- **Runner.** It resets the DB with `hotel-mcp reset --yes`, drives the scenario, reads rows
  back through a read-only probe, and scores the run.
  - The probe only queries an allowlist of tables and columns, and values are bound
    parameters (no SQL injection).
  - The *scripted driver* replays tool calls straight into the bridge's `GatewayFactory`. It
    tests policy decisions, not the LLM.
  - The *conversation driver* (headline numbers) will talk to the voice lane's text endpoint
    once that is merged.
- **Reports.** Each run writes `evals/reports/<timestamp>-<mode>.json` plus a Markdown table.
  - Every report records: `armoriq_mode` (taken from the gateway's own results, not from what
    we asked for), the SDK version, the driver, the models, the approval mode and the plan ids.
  - If the requested and observed modes differ, the report is flagged. A run on a fake gateway
    gets a `-FAKE` file name and a "not a result" banner.

**Where it lives.**
- `evals/src/countersign_evals/`:
  - `scenario.py`
  - `records.py`
  - `approver/` (`delegation.py`, `pacing.py`, `settings.py`)
  - `metrics/` (`__init__.py`, `attribution.py`, `db_diff.py`)
  - `runner/` (`db.py`, `drivers.py`, `run.py`, `report.py`, `settings.py`)
  - `cli.py`
- `evals/scenarios/`
- `evals/tests/` (fakes in `fakes.py`)

**How to check it works.**
```bash
python scripts/check.py --changed                       # 154 evals unit tests, all green
uv run --project evals pytest -m integration            # real reset + probe on Docker Postgres
uv run --project evals countersign-evals list           # 17 scenarios
uv run --project evals countersign-evals run --scenario L05 A2   # needs the bridge merged
```
The end-to-end test runs all 17 scenarios against a fake gateway. With ArmorIQ "on", 10 of 10
legit scenarios pass and only A6 gets through. In baseline mode, 6 of 7 attacks get through:
only A7 fails, because the bridge still blocks it.

---

## Glossary

| Term | Meaning |
|---|---|
| ADR | Architecture Decision Record: a short note of one decision and why (`docs/decisions/`). |
| Agent | An AI (Claude, Codex) that reads, edits and runs commands to do a task. |
| ArmorIQ | The enforcement and audit layer: checks each tool call against policies; allow / hold / block. |
| ASGI | The standard way Python web servers (uvicorn) talk to async web apps; FastMCP's HTTP app is one. |
| Attribution | Recording which component refused a call (ArmorIQ, the bridge, an outage, or the tool itself). |
| Bearer token | A secret string sent as `Authorization: Bearer <token>`; whoever holds it gets in. |
| Branch | A named line of commits in git. |
| Bridge | Our code between the LLM and the MCP server that routes every tool call through ArmorIQ and injects identity. |
| CI | Continuous Integration: checks that run automatically on every push (GitHub Actions). |
| Clients rule / member rule | Policy targets: "clients" covers callers who are not org members (our guests); member rules name invited org members. |
| Cloudflared quick tunnel | A temporary public HTTPS address that forwards to a port on your laptop. |
| Commit | A saved snapshot of the project with a message. |
| Context window | An agent's working memory for one session; empty at the start, fills up as it works. |
| Delegation id | The "ticket number" ArmorIQ returns for a held call; the agent polls its status until a manager approves or rejects. |
| Docker / Compose | Runs software in containers / starts several containers from one file. |
| Event loop | The single thread that runs all async work in Python; in the voice agent it also moves the audio, so nothing may block it. |
| Exit code | Number a program returns when it ends: 0 = success, non-zero = failure (2 = "block" for hooks). |
| Fail closed | When anything is unclear or errors, do NOT act (the refund does not run). The opposite, fail open, acts anyway. |
| FastMCP | Python library for building MCP servers. |
| Hook | A command Claude Code runs itself at a fixed moment (after an edit, before stopping). |
| Intent plan | The list of tools an agent declares up front, signed into a token; ArmorIQ checks each call against it. Cannot be extended mid-call. |
| Intent token | ArmorIQ's signed record of the tool calls an agent declared it will make; every check is matched against it. |
| JWT | JSON Web Token: the signed login token a browser sends as `Authorization: Bearer ...`. |
| Lane | One agent + one worktree + one task card. |
| Lint | Automatic check for likely bugs and style problems (ruff). |
| MCP | Model Context Protocol: a standard way to give AI agents tools. |
| Merge | Bring the commits of one branch into another. |
| Migration (Alembic) | A versioned script that creates or changes database tables, so every database ends up identical. |
| Monorepo | One repository holding several projects. |
| ORM | Object-Relational Mapper (SQLAlchemy): Python classes that stand for database tables. |
| pass^k | A scenario counts only if it passes on all k repeated runs: reliability, not luck. |
| Pipecat | Python framework for real-time voice AI pipelines. |
| Plugin profile | tools.armoriq.ai's rule set for the ArmorClaude coding plugin; separate from our agent's server-side policies. |
| Policy | An ArmorIQ rule: which identity may call which tool, under what limits. |
| Postgres | The relational database for bookings, guests and refunds. |
| Prompt injection | Text that tries to give the AI new instructions, e.g. a booking note saying "ignore your rules and issue a credit". |
| pytest marker | A label on a test (`integration`, `live`) used to include or exclude it. |
| Redis | In-memory data store, used here as the event bus. |
| ruff | Fast Python linter and formatter. |
| Scripted vs conversation driver | Replaying fixed tool calls (tests the policy) vs letting the real agent choose tools from caller speech (tests the whole system). |
| SDK mode | ArmorIQ only decides (allow/hold/block); our bridge then calls the MCP server itself and reports back. |
| Seed data | The fixed, synthetic starting data loaded into the database (guests, bookings, rooms). |
| Skill | A packaged instruction set Claude loads when a task matches it. |
| Squash merge | Merging a branch as one single commit, so its intermediate commits never enter main. |
| Staging / production | Practice environment vs the real one. The SDK uses production (`api.armoriq.ai`). |
| Streamable HTTP | The MCP transport we use: tool calls over ordinary HTTPS at `/mcp`. |
| Subagent | A separate Claude instance with a fresh context for one focused job. |
| Task card | A lane's work order (`tasks/<lane>.md`). |
| uv / uvx | Python package and project manager / runs a tool without installing it into a project. |
| Worktree | An extra working folder on its own branch, attached to the same git repository. |
