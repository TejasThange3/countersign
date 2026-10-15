# Lane: bridge

TASK: Build the governed tool gateway, the ArmorIQ bridge between the LLM and hotel-mcp. It
implements `ToolGateway` / `GatewayFactory` from `apps/agent/src/countersign_agent/contracts.py`.
Main owns that file, so don't edit it. This is the heart of the project:
- every tool call goes through ArmorIQ
- identity comes from verification
- holds never freeze the voice pipeline

CONTEXT (read first):
- AGENTS.md, all of it, especially product rules 1-5 and "Mistakes to never repeat".
- Scope sections 2 (who decides what, identity) and 4 (tools, policies, approvals, voice holds),
  and the "Day 1 findings that constrain the design" section.
- docs/research/armoriq-call-sequence.md: the proven call order, with file:line refs.
- docs/research/armoriq-day1-unknowns.md, section "Implications for the bridge". Where the two
  research docs disagree, the call-sequence doc and the spike win. For example, do NOT
  `await session.await_approval`, because it blocks the loop; use the spike's pattern instead.
- spikes/armoriq/src/armoriq_spike/. Port these into the bridge: copy and adapt them, because
  spikes are throwaway and may be deleted later.
  - sequence.py (governed_call)
  - approval.py (wait_for_approval, CheckedApprovals)
  - armoriq_setup.py
  - delegation.py
  - output.py and redact.py
- apps/mcp-server:
  - server.py: 17 tools, with tiers given by tags
  - verify_guest's return shape, which is pinned by its tests

FILES YOU OWN:
- apps/agent/src/countersign_agent/bridge/** and apps/agent/tests/bridge/**
- apps/agent/src/countersign_agent/cli_text.py: a text-mode REPL that drives one call by typing
  tool calls. The evals lane will reuse your factory, not this CLI.
- notes-drafts/bridge.md

DO NOT TOUCH:
- contracts.py
- apps/agent/pyproject.toml and uv.lock. The voice lane owns them. Main already added
  armoriq-sdk==0.6.10, fastmcp, pydantic-settings, httpx and pydantic. Ask for anything else
  under "Needs from main".
- apps/agent/src/countersign_agent/voice/** and app.py

DESIGN REQUIREMENTS:
1. One ArmorIQ session per call:
   - Open it with `for_user(identity).start_session()`.
   - At the start of the call, run one `start_plan` that declares every tool the LLM may use.
   - Re-plan only when identity changes (unverified to guest), and never while a hold is pending.
2. Identity state machine in the bridge:
   - A call starts as `ARMORIQ_USER_UNVERIFIED`.
   - A successful `verify_guest(booking_ref, last_name)` switches the ArmorIQ identity to
     `ARMORIQ_USER_GUEST` and stores the verified guest_id. Emit `identity_changed`.
   - Brute-force protection lives here, because ArmorIQ has no per-caller rate limit. After N
     failed verify attempts in one call (configurable, default 3), refuse further verify calls
     without calling the MCP server.
   - Staff identity is never granted over the phone.
3. guest_id injection:
   - Strip `guest_id` from every tool schema the LLM sees.
   - On every call, overwrite or insert the verified guest_id. If the caller is unverified and
     the tool needs a guest_id, refuse.
   - Never touch `target_guest_id` (used by the sensitive tools). ArmorIQ blocks those.
4. Tool discovery: use the fastmcp client's `tools/list` against `MCP_URL` with the bearer
   token, and take each tool's tier from its tags. Tools execute only through the governed path
   (product rule 1).
5. Holds:
   - `call()` returns PENDING immediately, with plan_id and delegation_id.
   - `wait()` uses the spike's approval wait: non-blocking, deadline-based, cancel-safe, with a
     checked mark-executed.
   - A timeout or a rejection means NOT_RUN.
6. `DISABLE_ARMORIQ=1`:
   - Same gateway, no ArmorIQ calls, every tool runs, and `armoriq_mode = "disabled"`.
   - Identity and injection rules stay exactly the same; only enforcement is removed. That way
     any difference in the eval results is down to ArmorIQ alone.
7. Fail closed everywhere: if ArmorIQ is unreachable or errors, return Decision.UNAVAILABLE and
   don't run the tool.
8. Measure ArmorIQ's overhead (plan + check) into `latency_ms`. Approval wait time doesn't count.
9. Events: emit a GatewayEvent for each step through the optional EventSink. Mask emails and
   never include secrets; reuse the spike's masking.
10. The LLM-facing `content` for blocks and holds must be short and neutral ("That needs a
    manager's approval." / "I can't do that."). It must never reveal policy names or thresholds.

HUMAN STEPS (ask the user, then wait; give exact click paths on platform.armoriq.ai):
- The user has invited `+unverified` and `+guest` as members. Turn policy `countersign-smoke`
  into the real policy. Rename it to `countersign` if the console allows. Keep it to one policy,
  because the quota is 2.
  - member rule `<unverified>`: allow the read tier, block everything else
  - member rule `<guest>`:
    - allow read and low-risk write
    - money tools: allow up to $100 and hold above. Find the amount-threshold field on each
      money tool row, and set it on ALL THREE money tools.
    - block the sensitive tier
  - clients/anyone fallback: block everything except the read tier, or the nearest the console
    allows
  - default for unlisted tools: block
  - Set every row explicitly and re-open the policy to confirm it saved (see the AGENTS.md
    mistakes list).
- Live verification against the real server instead of the toy:
  - Run hotel-mcp locally (docker compose Postgres + `hotel-mcp serve`) behind a cloudflared
    tunnel.
  - The user then updates the `hotel-mcp` URL in the console.

DONE MEANS:
- Unit tests, with clearly named fakes (`FakeArmorIQ...`), covering:
  - identity switch
  - the verify brute-force limit
  - guest_id stripping, injection and overwrite
  - target_guest_id left untouched
  - allow; hold then approve; hold then reject; hold timeout; block; unavailable
  - cancelling during wait
  - disabled mode
  - event masking
  - schema conversion
- A `live`-marked test or `cli_text.py` run against live ArmorIQ and the real hotel-mcp. It
  must show:
  - unverified refund: BLOCK
  - verified $40 refund: ALLOW, and the row is written
  - verified $250 refund: HOLD, then approved, and the row is written
  - export_guest_list: BLOCK

  Save masked evidence JSON with the plan ids.
- `python scripts/check.py --changed` is green, the reviewer says PASS, and Codex says PASS
  (max 3 rounds).
- notes-drafts/bridge.md is written in the AGENTS.md notes format.

Start by showing me your plan before editing.
