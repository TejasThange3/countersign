## 16. The ArmorIQ bridge: the governed tool gateway

**Analogy.** Think of the front-desk clerk (the voice agent) as someone who can only *ask* for
things to be done. Every request goes through one door with a guard behind it (the bridge).
The guard does four jobs. First, they check the caller's ID card: until the caller has proved
who they are (verify_guest), they are a stranger, and once verified the guard writes the
guest's room number onto every request form, crossing out any number the clerk scribbled
there. Second, they radio the security office (ArmorIQ) with each form, and the office says
*go*, *wait for the manager*, or *no*. Third, they carry the errand out on the hotel's back
office system (hotel-mcp), but only after a *go* or the manager's *yes*. Fourth, they black
out names, emails and phone numbers on every copy that goes on the noticeboard (the event log
and the dashboard). A stranger who gets the ID check wrong three times is turned away without
anyone radioing the office.

**Technical explanation.** The bridge implements the `ToolGateway` / `GatewayFactory`
contract from `contracts.py`. The voice pipeline (or the text CLI) asks for one gateway per
phone call and sends every tool call through `gateway.call(name, args)`.

- **Identity** (`identity.py`, `gateway.py`). Each call starts as the *unverified* ArmorIQ
  user. A successful `verify_guest` switches the call to the *guest* user and stores the
  guest's id. From then on the bridge **injects `guest_id`** into every guest-scoped tool and
  overwrites whatever the model sent (product rule 3). Re-verifying as the same guest does
  nothing. Re-verifying as a *different* guest is refused (`other_guest`), so a caller can't
  hop from one booking to another mid-call. After `ARMORIQ_VERIFY_MAX_ATTEMPTS` (default 3)
  failed tries, the call is locked out (`verify_locked_out`). The lockout is the only refusal
  that skips the ArmorIQ check, because no tool would run anyway.
- **Every call goes through ArmorIQ first** (`enforcer.py`), `verify_guest` included (product
  rule 1). Each identity gets one ArmorIQ session per phone call and one plan (`start_plan`)
  that declares all the tools. Each tool call is then `check` -> verdict:
  - allow: the tool runs
  - hold: the bridge waits for a human approval
  - block: the tool doesn't run
  - anything unexpected (a hold with no approval id, an "enforce-unavailable" error, a
    network failure): **fail closed**, so the tool doesn't run.

  All SDK calls are blocking HTTP, so they run in `asyncio.to_thread`, which keeps the voice
  pipeline's event loop free.
- **Holds** (`approval.py`, `delegation.py`). `gateway.call` returns a *hold* result at once,
  so the agent can say "let me check with a manager" instead of going silent.
  `gateway.wait(hold_id)` polls ArmorIQ in a worker thread. When the hold is approved, it
  marks the approval as used (`CheckedApprovals`, which fails closed if ArmorIQ refuses), runs
  the tool, and reports it. While a hold is pending, an unverified caller can't run
  `verify_guest` to switch identity under it. The hold is recorded inside the identity lock, so
  a `verify_guest` that runs at the same moment still sees it. If ArmorIQ itself reuses an
  earlier approval (`check()` answers allow with a delegation id), the bridge refuses it
  (`approval_reused`). The SDK matches that approval by tool + amount + plan, not by the
  arguments, so a second $250 refund for another booking could otherwise spend the first
  refund's approval. Approvals are spent only through `wait()`, with the arguments that were
  held.
- **Each call holds its identity until it is done.** Check, run and report all happen under
  one per-call lock. So a `verify_guest` that arrives meanwhile waits for in-flight tools,
  and each tool is reported through the ArmorIQ session that allowed it. The cost: one phone
  call's tool calls run one at a time.
- **One plan at a time per process.** The SDK mints a plan's token from one field on the
  shared client that every new session overwrites. If two phone calls started a plan at the
  same moment, one could get a token for the other caller's identity. So "open session + start
  plan" runs as one step on a single dedicated thread (`enforcer.PLAN_EXECUTOR`), never on the
  shared pool that every call's check, report and approval polls use.
- **Tools** (`tools.py`, `executor.py`). `McpExecutor` talks to hotel-mcp over FastMCP's
  streamable HTTP client with the bearer token. Each MCP tool carries exactly one tier tag:
  read, write, money or sensitive. A tool without one is dropped and is never shown to the
  model. The bridge strips `guest_id` from the schemas the model sees, so the model can't
  even propose one.
- **Masking** (`masking.py`). Every event and log line is masked before it leaves the bridge:
  secrets and personal fields (`email`, `first_name`, `last_name`, `phone`, `guest_name`) are
  blanked, even inside tool results that travel as JSON text, and any stray email address
  becomes `<email>`.
  The model still sees the real tool result; only published copies are masked.
- **Factory** (`factory.py`). Builds the ArmorIQ client lazily, in a worker thread. If the
  client can't be built (bad key, no network), the call gets an `UnavailableEnforcer` that
  refuses every tool with `armoriq_unreachable`. The next call tries again.
  `DISABLE_ARMORIQ=1` gives the baseline `DisabledEnforcer` (everything runs, and each
  verdict says `armoriq_disabled`).
- **Plan steps are pinned to `ARMORIQ_MCP_NAME`** (`armoriq_setup.py`). The SDK would
  otherwise look tools up in a flat tool -> server map, which can pick a leftover test server
  that shares tool names.
- **The policy** (`docs/research/armoriq-policy-countersign.md`). It is set by hand in the
  ArmorIQ console on `hotel-mcp-2` and has one override per identity. The unverified caller
  can only read. The verified guest can read and write, every money call **holds** for a
  manager, and the sensitive tools are blocked. The planned "allow up to $100" rule turned out
  not to be possible: the console's parameter limits are stored but not enforced, so a $250
  refund was allowed. The money limit isn't rebuilt in our code, because ArmorIQ must make
  that decision. Two more console lessons: an override *replaces* the base rows, and
  "Default" inside an override means Block.
- **Reason codes are a contract** read by the evals lane: `verify_locked_out`, `not_verified`,
  `unknown_tool`, `hold_pending`, `other_guest`, `no_plan`, `enforce_error`,
  `armoriq_disabled`, `armoriq_unreachable` (plus `enforce_unavailable`,
  `hold_without_delegation`, `approval_error`, `approval_reused`, `unknown_hold`,
  `wait_in_progress`, `approved`, `rejected`, `timeout`). Count refusals by `reason`, not by
  `decision`. In particular, `other_guest` comes back with `decision=allow, outcome=ran`,
  because `verify_guest` really did run. ArmorIQ allowed it, the MCP looked up the other
  guest, and the run was reported to ArmorIQ. What the bridge refuses is the identity switch:
  the call stays on the first guest and the other guest's details are withheld. Reporting it
  as BLOCK / NOT_RUN would misstate what ran. A second `wait` on a hold that is already being
  waited on returns `wait_in_progress`: the first wait decides, so the tool can never run
  twice.

**Where it lives.** `apps/agent/src/countersign_agent/bridge/` (gateway, factory, enforcer,
identity, tools, executor, approval, delegation, masking, redact, settings, armoriq_setup),
`apps/agent/src/countersign_agent/cli_text.py` (text REPL), and the tests in
`apps/agent/tests/bridge/` (unit tests use `Fake*` ArmorIQ stand-ins; `test_live_bridge.py`
is the live proof). The policy is written down in
`docs/research/armoriq-policy-countersign.md`.

**How to check it works.**
- Unit tests: `uv run --project apps/agent pytest -q apps/agent/tests/bridge`. They should all
  pass, and the live test shows as skipped (`tests/bridge/conftest.py` only lets it run with
  `-m live`).
- By hand: start hotel-mcp, then run
  `uv run --project apps/agent python -m countersign_agent.cli_text`. Try `specs`, then
  `call issue_refund {"amount": 40}`: it is blocked while you are unverified. Then
  `verify LRK-1001 Okafor`, then `call issue_refund {"booking_id": 1, "amount": 40}`. It
  holds; approve it in the ArmorIQ console, then type `wait`, which waits for the last held
  call and runs it once approved.
- Live proof (real ArmorIQ, needs hotel-mcp and the tunnel up):
  `uv run --project apps/agent pytest -m live apps/agent/tests/bridge/test_live_bridge.py -s`.
  You should see `1 passed`. The steps are: unverified refund BLOCK, verify ALLOW, $40 HOLD ->
  approved -> payment row written, $250 HOLD -> rejected -> no row, export BLOCK. It writes
  masked evidence to `apps/agent/tests/bridge/evidence/` (first passing run:
  `20261015T110948Z-live-bridge.json`; the run on the final code is `20261015T115551Z-live-bridge.json`).
