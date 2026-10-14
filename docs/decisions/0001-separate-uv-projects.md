# 0001: One uv project per app, not a single workspace

**Status:** accepted (2026-10-14)

**Context.** Several agents work in parallel, each in its own git worktree on its own branch.
With a single uv workspace there is one root `uv.lock`, and any lane that adds a dependency
rewrites it, so every merge conflicts on the lockfile.

**Decision.** `apps/mcp-server`, `apps/agent`, `evals` (and each `spikes/*`) are independent uv
projects, each with its own `pyproject.toml` and `uv.lock`. Shared lint config lives in the root
`ruff.toml`; `scripts/check.py` discovers every project automatically.

**Consequences.** Lanes never conflict on dependencies. Cost: code shared between projects
(for example event schemas used by both the agent and the evals) must be either duplicated
briefly or moved into a small shared package later. Revisit if that becomes painful.
