# 0002: Agents fix their own errors before handing work back

**Status:** accepted (2026-10-14)

**Context.** Several agents run in parallel, and the human reviewing their work is the
bottleneck. Work that comes back broken wastes the scarcest resource.

**Decision.** Four automatic loops, from fastest to slowest:
1. PostToolUse hook (`.claude/hooks/after_edit.py`): ruff formats and fixes every Python file on
   edit and reports leftovers to the agent immediately.
2. Stop hook (`.claude/hooks/stop_gate.py`): the agent cannot finish while
   `scripts/check.py --changed` fails. It gets at most 3 forced retries per session, then it may
   stop and must report what is still red.
3. Two independent reviews: the `reviewer` subagent (Claude, fresh context), then Codex
   (`scripts/codex_review.py`, ChatGPT, read-only sandbox). MUST FIX items get fixed, up to 3
   Codex rounds.
4. Learning: a mistake that repeats becomes a line in AGENTS.md "Mistakes to never repeat".

**Consequences.** Slower per-lane completion, much less human rework. Every loop has a hard cap,
so an agent can never spin forever. CI runs the same `scripts/check.py`, so local green means CI
green.
