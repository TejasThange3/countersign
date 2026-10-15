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
  `verify_guest` to switch identity under it.
- **Tools** (`tools.py`, `executor.py`). `McpExecutor` talks to hotel-mcp over FastMCP's
  streamable HTTP client with the bearer token. Each MCP tool carries exactly one tier tag:
  read, write, money or sensitive. A tool without one is dropped and is never shown to the
  model. The bridge strips `guest_id` from the schemas the model sees, so the model can't
  even propose one.
- **Masking** (`masking.py`). Every event and log line is masked before it leaves the bridge:
  secrets and personal fields (`email`, `last_name`, `phone`) are blanked, and any stray
  email address becomes `<email>`.
- **Factory** (`factory.py`). Builds the ArmorIQ client lazily, in a worker thread. If the
  client can't be built (bad key, no network), the call gets an `UnavailableEnforcer` that
  refuses every tool with `armoriq_unreachable`. The next call tries again.
  `DISABLE_ARMORIQ=1` gives the baseline `DisabledEnforcer` (everything runs, and each
  verdict says `armoriq_disabled`).
- **Plan steps are pinned to `ARMORIQ_MCP_NAME`** (`armoriq_setup.py`). The SDK would
  otherwise look tools up in a flat tool -> server map, which can pick a leftover test server
  that shares tool names.
- **Reason codes are a contract** read by the evals lane: `verify_locked_out`, `not_verified`,
  `unknown_tool`, `hold_pending`, `other_guest`, `no_plan`, `enforce_error`,
  `armoriq_disabled`, `armoriq_unreachable` (plus `enforce_unavailable`,
  `hold_without_delegation`, `approval_error`, `unknown_hold`, `approved`, `rejected`,
  `timeout`).

**Where it lives.** `apps/agent/src/countersign_agent/bridge/` (gateway, factory, enforcer,
identity, tools, executor, approval, delegation, masking, redact, settings, armoriq_setup),
`apps/agent/src/countersign_agent/cli_text.py` (text REPL), and the tests in
`apps/agent/tests/bridge/` (unit tests use `Fake*` ArmorIQ stand-ins; `test_live_bridge.py`
is the live proof). The policy is written down in
`docs/research/armoriq-policy-countersign.md`.

**How to check it works.**
- Unit tests: `uv run --project apps/agent pytest -q tests/bridge`. They should all pass, and
  the live test is skipped.
- By hand: start hotel-mcp, then run
  `uv run --project apps/agent python -m countersign_agent.cli_text`. Try `specs`, then
  `call issue_refund {"amount": 40}`: it is blocked while you are unverified. Then
  `verify LRK-1001 Okafor`, `call issue_refund {"amount": 40}` (allow) and
  `call issue_refund {"amount": 250}` (hold), followed by `wait` (it waits for the last held call).
- Live proof (real ArmorIQ, needs hotel-mcp and the tunnel up):
  `uv run --project apps/agent pytest -m live tests/bridge/test_live_bridge.py -s`. It writes
  masked evidence to `apps/agent/tests/bridge/evidence/`.
