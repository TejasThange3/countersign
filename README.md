# Countersign

**A voice agent that can't be talked into anything.** Countersign is a real-time voice front desk
for a boutique hotel, The Larkspur. It takes real actions (bookings, refunds, credits) against a
real database, and **every tool call goes through ArmorIQ before it runs**: ArmorIQ allows it,
holds it for a human manager, or blocks it.

- **Live demo:** https://countersign-aimcp.vercel.app/try (voice or text; demo guest `LRK-1001` / `Okafor`)
- **Demo video:** _link added on submission_
- **Built for:** Flow State 2026 (ArmorIQ), Oct 13-17, 2026

## Problem and pitch

Voice agents are being trusted with money and personal data, and anything a caller says goes
straight into the model's context. A model can be flattered, rushed, impersonated at, or
prompt-injected through a booking note. Countersign accepts that the model *can* be talked
into wanting something, and makes sure it still can't *make it happen*:

- read-only lookups run for anyone;
- changes to a booking run only after the caller is verified;
- **every refund, credit and fee waiver is held** until a manager approves it;
- guest exports, cancelling other people's bookings and staff access are **blocked outright**.

Those decisions are made by ArmorIQ against a signed plan and a policy, not by our code and
not by the model.

## Architecture

```
 Browser (/try page)                                    Judge / visitor
   mic 16 kHz PCM ──WebSocket /voice──┐    text ──HTTP /text/calls──┐
                                      v                             v
 ┌───────────────────────────── Agent server (FastAPI + Pipecat) ─────────────────────────────┐
 │  audio in → Silero VAD → Groq Whisper large-v3-turbo (ElevenLabs Scribe fallback)           │
 │           → LLM: gpt-oss-120b on Groq (20b fallback), tool calling                          │
 │           → ElevenLabs TTS (Flash v2.5) → audio out                                         │
 │                                                                                             │
 │  every tool call → Countersign bridge (ArmorIQ core Python SDK)                             │
 │                     • owns identity: unverified → verified guest, injects guest id          │
 │                     • start_plan (signed intent token) → check → ALLOW / HOLD / BLOCK       │
 │                     • ALLOW: bridge calls hotel-mcp, then report                            │
 │                     • HOLD: waits for the manager's decision (hold music meanwhile)         │
 │                     • BLOCK: never runs; the agent is told plainly                          │
 │  decision events → browser (decision log, manager card)                                     │
 └──────────────────────────────────────────┬──────────────────────────────────────────────────┘
                                            │ streamable HTTP /mcp, bearer token
                                            v
                        hotel-mcp (FastMCP, 17 tools) → Postgres (synthetic data)

 ArmorIQ (platform.armoriq.ai): MCP + agent registration, member identities, Policy Studio,
 approvals (delegation API), audit trail.
```

Hosting: agent, hotel-mcp and Postgres on Railway; the website on Vercel.

**How a call works.** The caller speaks; Silero voice detection decides when they've finished;
Whisper transcribes; the model decides which hotel tool to call. The model only *proposes* a
tool call. The bridge turns it into an ArmorIQ plan step, asks ArmorIQ for a decision, and only
on ALLOW does it call hotel-mcp. The result goes back to the model, which answers in one to
three spoken sentences.

### Who decides what

| Part | Decides |
|---|---|
| **ArmorIQ** (policy in the console) | May this identity call this tool? Allow, hold, or block |
| **Bridge** | Who the caller is. It injects the verified guest id and overwrites whatever the model put there |
| **hotel-mcp** | Business logic only, scoped to the guest record it's given. No permission logic |
| **Model** | Nothing final. It proposes; it never picks whose data a tool touches |

## How ArmorIQ is used

ArmorIQ ships adapters for LangChain, Google ADK, Strands and CrewAI, but none for Pipecat or
any voice framework. So Countersign includes **a small ArmorIQ-to-Pipecat bridge** on the core
Python SDK (sdk mode), following the same lifecycle as the official Strands adapter
([`apps/agent/src/countersign_agent/bridge/`](apps/agent/src/countersign_agent/bridge/)):

1. **Session per identity.** `client.for_user(email).start_session()`. Each call starts as the
   `+unverified` member; after `verify_guest` succeeds, the bridge switches the call to the
   `+guest` member. The model can't change identity by saying "I'm the manager".
2. **Signed plan.** `start_plan(tool_calls, goal)` returns an intent token; later tool calls
   extend the same plan.
3. **Check before every call.** `session.check(...)` → `/iap/sdk/enforce` → allow, hold or block,
   with ArmorIQ's reason (`enforcement_passed`, `rule_action_hold`, `tool_denied`,
   `tool_not_in_allowlist`) passed through unchanged.
4. **Run, then report.** On allow the bridge calls hotel-mcp itself, then `session.report(...)`
   so the plan reaches `completed`.
5. **Holds.** The bridge polls the delegation status off the event loop (`asyncio.to_thread`;
   the SDK's polling is synchronous and would freeze the audio). The caller hears hold music,
   then a fixed sentence for the outcome (approved and done / declined / no answer).

### Policy (Policy Studio)

Default action **Block**. Every row is set explicitly in each member override (an override
*replaces* the base rows, and "Default" inside an override means Block).

| Tool | `+unverified` | `+guest` |
|---|---|---|
| verify_guest, get_booking, check_availability, get_hotel_info, get_cancellation_policy | Allow | Allow |
| create_booking, modify_booking_dates, add_booking_note, request_housekeeping, cancel_own_booking | Block | Allow |
| issue_refund, apply_comp_credit, waive_fee | Block | **Hold** |
| export_guest_list, cancel_any_booking, delete_guest_profile, grant_staff_access | Block | Block |

Full write-up, including what we learned probing the console:
[docs/research/armoriq-policy-countersign.md](docs/research/armoriq-policy-countersign.md).

### Approvals: why a human, and who that is in the demo

Money always waits for a person. That's the point: the agent can be fooled, the policy can't,
and a human signs off on anything that moves money.

On the live demo there's no hotel manager on duty, so **you play the manager**. When a refund is
held, a card appears with Approve and Reject. Your click goes to ArmorIQ's real delegation API
(`/delegation/approve` or `/delegation/reject`, as the organisation's approver), scoped to that
call's own held request; the browser never chooses which request it decides. ArmorIQ records it
in its audit log, and the agent learns the outcome from ArmorIQ, not from the browser. In a real
hotel the same request would go to a manager in the ArmorIQ console. No answer in 60 seconds
means it's refused.

## Proof of ArmorIQ

Live console traces, from real calls through the bridge:

| Allowed | Blocked | Held, then approved |
|---|---|---|
| ![allow](docs/proof/armoriq-allow.png) | ![block](docs/proof/armoriq-block.png) | ![hold approved](docs/proof/armoriq-hold-approved.png) |

The live bridge test (`apps/agent/tests/bridge/test_live_bridge.py`, run with `-m live`) records
masked evidence in [`apps/agent/tests/bridge/evidence/`](apps/agent/tests/bridge/evidence/):

| Case | ArmorIQ decision | Reason | Result |
|---|---|---|---|
| Unverified caller, `issue_refund` $40 | BLOCK | `tool_denied` | not run |
| `verify_guest` LRK-1001 | ALLOW | `enforcement_passed` | ran; call switches to `+guest` |
| Guest `issue_refund` $40 | HOLD | `rule_action_hold` | approved → payment row written |
| Guest `issue_refund` $250 | HOLD | `rule_action_hold` | rejected → nothing written |
| Guest `export_guest_list` | BLOCK | `tool_denied` | not run |

## Try it

On https://countersign-aimcp.vercel.app/try pick **Voice** or **Text** and follow the script:

1. "Do you have a room from November 2nd to 4th for two people?" → **allowed**
2. "My booking reference is LRK-1001, last name Okafor." → **verified**
3. "I'd like a 40 dollar refund on that booking." → **held for you** → Approve or Reject

Then open **Now try to break it**: authority claims, a spoken prompt injection, someone else's
booking, swapping a refund for a credit, splitting a refund, a prompt injection hidden in a
booking note (LRK-1007), verification brute force, and off-topic questions. Every decision
appears in the log with what ArmorIQ decided and why.

## Evaluation

[`evals/`](evals/) holds an automated caller and 17 scenarios: 10 legitimate calls (L01-L10) and
7 attacks (A1-A7: authority impersonation, spoken injection, injection from a booking note,
cross-guest access, tool swapping, refund splitting, verification brute force). The runner
resets the database, drives each scenario with ArmorIQ live and again with `DISABLE_ARMORIQ=1`,
and scores the **database**, not the transcript.

```bash
uv run --project evals countersign-evals run                 # ArmorIQ live, automated approver
uv run --project evals countersign-evals run --baseline      # same agent, no ArmorIQ
```

Reports land in `evals/reports/` and record `armoriq_mode`.

## Setup from a clean clone

You need: Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 20+, Docker, and accounts for
ArmorIQ (platform.armoriq.ai), Groq and ElevenLabs.

```bash
cp .env.example .env                                   # every variable is commented
docker compose -f infra/docker-compose.yml up -d       # Postgres + Redis
uv run --project apps/mcp-server hotel-mcp migrate
uv run --project apps/mcp-server hotel-mcp seed
uv run --project apps/mcp-server hotel-mcp serve       # http://localhost:8000/mcp
uv run --project apps/agent countersign-agent          # http://localhost:7860
cd apps/dashboard && npm install && npm run dev        # http://localhost:3000/try
```

**ArmorIQ console steps**
1. Settings → API Keys: create a key (`ARMORIQ_API_KEY`).
2. MCP Servers: register hotel-mcp by its public `/mcp` URL with the bearer token, and scan its tools.
3. Agents: register `countersign`.
4. Members: add two members for the caller identities (`ARMORIQ_USER_UNVERIFIED`, `ARMORIQ_USER_GUEST`).
5. Policy Studio: create the policy above, targeting the MCP server, default Block, with an
   explicit override for each member. Check the saved state with `resolve-user`.

For the website, set `CORS_ORIGINS` on the agent to the site's origin and
`NEXT_PUBLIC_AGENT_URL` on the site to the agent's URL.

Checks: `python scripts/check.py` (lint, format and unit tests for every project).

## Sandbox note

All guests, bookings and payments are synthetic seed data. Refunds and credits are database
rows; no payment provider is ever called. No real customer data is used. Website voice calls are
streamed for transcription only and are not recorded or stored.

## Disclosure

- **AI coding assistants:** Claude Code (main development) and OpenAI Codex (automated code review).
- **Main libraries and services:** ArmorIQ Python SDK, Pipecat, FastAPI, FastMCP, SQLAlchemy,
  asyncpg, Alembic, Silero VAD, Groq (LLM and Whisper STT), ElevenLabs (TTS, Scribe STT
  fallback), Next.js, Tailwind CSS, Motion, Phosphor Icons. The corner-bracket button is after
  the Corner Button idea in Vengeance UI.
- **Pre-existing code:** none. All project code was written during the hackathon window
  (first commit Oct 14, 2026).

## What broke and how we fixed it

- **ArmorIQ ignored amount limits.** `amount <= 100` is stored in the console but not enforced
  (refunds of $250 were allowed). Every money call now holds instead, and a human decides.
- **Member overrides replace the base rows.** A partial override silently blocked every tool it
  didn't list. Each override now lists every tool, verified read-only with `resolve-user`.
- **Duplicate tool names.** A toy MCP server from day 1 can't be deleted and shares three tool
  names with the real one, so ArmorIQ evaluated those against the toy server
  (`no_matching_policy`). Fixed with a second policy targeting the toy server with the same rows.
- **The voice pipeline froze during holds.** The SDK's approval polling is synchronous; it now
  runs in `asyncio.to_thread`.
- **The model said "still pending" after a manager approved.** Hold outcomes are now fixed
  sentences spoken verbatim, not left to the model.
- **The model skipped verification after wrong guesses**, so the brute-force lockout never
  fired. The prompt now requires `verify_guest` for every reference given.
- **Whisper echoed its own prompt as a transcript.** The STT prompt is off.
- **Text chat asked visitors to confirm what they had just typed.** Website text calls get a
  short typed-chat prompt section (opt-in; evals keep phone behaviour).
- **Deploying to Railway:** BuildKit cache mounts rejected, an `.env` lookup that assumed the
  repo layout crashed the container, port mismatches, an empty database reference. Each fixed
  and noted in [notes.md](notes.md).

## Repository layout

```
apps/mcp-server/   hotel-mcp: FastMCP server, models, migrations, seed
apps/agent/        Pipecat pipeline, FastAPI app, ArmorIQ bridge
apps/dashboard/    Next.js website and /try console
evals/             caller simulator, scenarios, approver, metrics, reports
spikes/armoriq/    day-1 ArmorIQ experiments and evidence
docs/              architecture, decisions, proof screenshots, research
notes.md           learning log
```
