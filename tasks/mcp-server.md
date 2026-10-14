# Lane: mcp-server

TASK: Build `hotel-mcp`, the FastMCP server with the hotel front-desk tools, backed by Postgres
with synthetic seed data and bearer-token auth, ready to deploy as one Docker image.

CONTEXT: scope sections 2 ("Who decides what"), 4 (tools by risk tier, seed data), 6
("MCP server"), 7. AGENTS.md product rules 2, 3, 4 and 6 apply directly here.

FILES YOU OWN:
- apps/mcp-server/** (code, tests, alembic migrations, seed, Dockerfile, its pyproject/uv.lock)
- infra/railway.json (granted to this lane)
- notes-drafts/mcp-server.md

DO NOT TOUCH: everything else. If you need Postgres in infra/docker-compose.yml changed, or a
new variable in .env.example, list it under "Needs from main" in your report.

HUMAN STEPS (ask, then wait): none to build it. Deploying to Railway and registering the
URL in the ArmorIQ console happen after this lane is merged.

DONE MEANS:
- FastMCP server on streamable HTTP at `/mcp`, listening on `$PORT`.
- Every tool from scope section 4, grouped by tier, with clear docstrings (the model reads them)
  and typed arguments. Money tools take `amount` (a decimal number of dollars) and `reason`.
- Tools that act on a guest take that guest/booking id as an explicit argument (the bridge
  injects it) and only touch rows belonging to it. No permission or limit checks in this server.
- Requests without the correct `Authorization: Bearer $MCP_BEARER_TOKEN` are rejected.
- SQLAlchemy async models + an alembic migration; `seed` command loads ~30 guests, ~50 bookings,
  rooms, a few payments, and one booking whose note contains a planted prompt injection
  (all synthetic). A `reset` command restores the seed state (the eval runner needs it).
- Dockerfile that runs the server on `$PORT`.
- Tests: unit tests for tool logic and data scoping; integration tests (marked `integration`)
  against the Docker Postgres for migrations + seed + one tool per tier; an auth test proving
  a missing/wrong token is rejected.
- `python scripts/check.py --integration` green, reviewer PASS, Codex review PASS (max 3 rounds).
- apps/mcp-server/README.md: how to run locally, env vars, seed/reset commands.
- notes-drafts/mcp-server.md written in the AGENTS.md notes format.

Start by showing me your plan before editing.

## Update from main (Oct 14, from the armoriq-smoke lane)

- ArmorIQ's optional security scan fails on a bearer-protected server: the scanner sends no
  token. Keep auth on every request; we accept "Unscanned" (it is optional). Do not open
  initialize/tools/list without auth.
- The server must refuse to start with an empty MCP_BEARER_TOKEN (an empty token silently
  disabled auth on the toy server).
- ArmorIQ never calls the MCP URL while enforcing in sdk mode; only the bridge does.
