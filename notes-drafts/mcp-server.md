## N. hotel-mcp: the hotel's back office

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

Glossary additions: MCP, streamable HTTP, ASGI, ORM, migration (Alembic), seed data, prompt
injection, bearer token.
