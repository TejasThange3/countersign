# ArmorIQ call sequence for the Countersign bridge

Lane `armoriq-smoke`, 2026-10-14. SDK `armoriq-sdk==0.6.10` (pinned in `spikes/armoriq`).
Backend `https://api.armoriq.ai`, console `platform.armoriq.ai`. Every live result below comes
from `spikes/armoriq/smoke.py` runs saved in `spikes/armoriq/evidence/` (`armoriq_mode: live`,
identities masked as `<guest>`, `<manager>`, `<unverified>`, `<admin>`).

Source references are to files inside the installed package
(`spikes/armoriq/.venv/Lib/site-packages/armoriq_sdk/`).

## 1. Which mode, which console

- **Mode: `sdk`.** All official adapters (Strands, LangChain, Google ADK) default to
  `mode="sdk"`: ArmorIQ decides, then the agent itself calls the MCP server, then reports.
  `strands.py:59-69`, `langchain.py:64`, `google_adk.py:63`. The proxy mode
  (`session.dispatch` -> `client.invoke`) exists but no adapter uses it; we don't either.
- **Console: platform.armoriq.ai.** The SDK talks to `api.armoriq.ai`, `iap.armoriq.ai`,
  `proxy.armoriq.ai` (`client.py:87-89`, `_build_env.py:36-38`) and links only to
  `platform.armoriq.ai/dashboard/api-keys` (`client.py:181`). tools.armoriq.ai is never
  referenced, and live checks found none of our traffic there (Q9).

## 2. The call order to copy (from the Strands integration)

One client per process, one session per (user, call session). `integrations/strands.py`:

| Step | When | SDK call | HTTP | Source |
|---|---|---|---|---|
| 0 | process start | `ArmorIQClient(api_key=..., agent_id="countersign")` | `GET {proxy}/health` (key check) | `client.py:103`, `:472` |
| 0b | process start, once | `client.bootstrap()` -> `toolMap` -> tool-name parser | `POST /iap/sdk/bootstrap` | `client.py:314`; parser `strands.py:90-108` |
| 1 | per user | `client.for_user(email).start_session(SessionOptions(mode="sdk", tool_name_parser=..., default_mcp_name="hotel-mcp"))` | none | `strands.py:110-127`, `:193-206`; `client.py:374`, `:1817` |
| 2 | after the LLM picks tool calls | `session.start_plan([{name, args}...], goal)` = plan capture + intent token. Declare only the calls this turn chose. Idempotent per plan hash. | `POST /iap/sdk/token` | `strands.py:208-218`, `:250-258`; `session.py:393`, `:447-495` (`capture_plan` `:484`, `get_intent_token` `:485`, `client.py:551`, `:580`, `:607`) |
| 3 | before each tool runs | `decision = session.check(tool, args, user_email=email)` -> `EnforceResult(allowed, action, reason, delegation_id, matched_policy)` | `POST /iap/sdk/enforce` | `strands.py:275`; `session.py:986`, `:1037`, `:786-864` (`:813`) |
| 3a | a tool not declared in step 2 | blocked locally, `tool-not-in-plan`, no HTTP | none | `session.py:799-809` |
| 3b | `action == "hold"` | inside `check`: reuse an approved delegation for this plan, else create one; returns hold + `delegation_id` without blocking | `POST /delegation/check-approved`, `POST /delegation/request` | `session.py:1200-1292`; `client.py:1569`, `:1544` |
| 4 | on hold | Strands: `await session.await_approval(delegation_id, timeout=..., interval=5.0, user_email=email)` -> `approved` / `rejected` / `timeout`; on approval it marks the delegation executed. **This blocks the event loop** (see below), so the bridge uses `wait_for_approval(client, delegation_id, ...)` instead: the same loop with each HTTP call in `asyncio.to_thread`. | `GET /delegation/{id}/status` every `interval`; `POST /delegation/mark-executed` | `strands.py:279-312`; `session.py:1294-1338`; `client.py:1597`, `:1617`; ours: `spikes/armoriq/src/armoriq_spike/approval.py` |
| 5 | allow or approved | **the bridge calls hotel-mcp itself** | MCP `tools/call` | — |
| 6 | after the tool ran (success or tool error) | `session.report(tool, args, result, ReportOptions(status=...))`, off the event loop | `POST /iap/audit` | `strands.py:324-365`; `session.py:1065-1153` (`:1107`) |

Rules the adapters follow, which the bridge must keep:
- **Fail closed.** Only an explicit allow or an approved hold runs the tool. Block, rejected,
  timeout and any exception in check cancel it (`strands.py:260-322`).
- **Never report what did not run.** Cancelled calls skip step 6 (`strands.py:331-333`).
- **Report tool errors too**, with `status="error"` (`strands.py:345-357`).
- **Never run an SDK network call on the event loop.** `start_plan`, `check`, `report`,
  `bootstrap` and the `ArmorIQClient` constructor (it checks the key over HTTP) are blocking
  httpx calls: run them via `asyncio.to_thread`.
- **Do not `await session.await_approval(...)` in the voice pipeline.** It is declared `async`
  but calls the synchronous `client.get_delegation_status` and `client.mark_delegation_executed`
  directly on the loop (`session.py:1319`, `:1331`), so every poll freezes the loop for a full
  HTTP round trip. Measured with a 250 ms fake status call: the SDK's wait stalled the loop
  251 ms; `wait_for_approval` (same loop, calls offloaded) at most 17 ms. The Strands and
  LangChain adapters inherit this stall. `wait_for_approval` keeps the SDK's semantics
  (sleep first, transient 429/502/503/504 back off and keep waiting, other errors propagate so
  the caller fails closed, mark executed for this plan on approval) with two stricter
  deviations: the window is a monotonic deadline that includes network time (the SDK counts
  only its sleeps, so slow polls stretch it), and an approval arriving after the deadline is a
  `timeout`, so a late "yes" can never run a tool the caller was told had timed out; and an
  `expired` delegation ends the wait at once as `timeout`. Its sleeps stay on the loop, so
  cancelling the wait (caller hung up) stops polling. Covered by
  `tests/test_approval.py::test_event_loop_stays_responsive_while_polls_block`.
- **SDK `mark_delegation_executed` discards HTTP errors: check it yourself.** It posts via
  `_retry_post`, which returns the last response even for a 4xx or an exhausted 5xx, and never
  checks it (`client.py:257-294`, `:1617-1637`), so a refused "mark executed" still lets the
  tool run. The bridge must use `CheckedApprovals(client)` (`approval.py`): same request, same
  retry and Idempotency-Key, and it raises unless the answer is 2xx, so the call fails closed.
  Covered by `tests/test_checked_approvals.py` (real `ArmorIQClient`, fake HTTP transport).
- Keep the approval poll at a few seconds; delegation routes are rate limited (~30-60/min).

LangChain does the same: plan in `on_llm_end`, check in `on_tool_start`, report from
`on_tool_end` / `on_tool_error` (`langchain.py:213`, `:237`, `:251`, `:290-305`, `:407-420`).

Our implementation of this order, with unit tests: `spikes/armoriq/src/armoriq_spike/sequence.py`
(`governed_call`) and `armoriq_setup.py`.

## 3. Approver side (not in the SDK)

The SDK only requests and polls delegations. Deciding one is raw HTTP, API-key auth:

```
GET  /delegation/my-role     X-API-Key, X-User-Email: <approver>   -> {role, limit}
POST /delegation/approve     X-API-Key, X-User-Email: <approver>
     {delegationId, approverEmail, approverRole, approverLimit}    -> 201 {status: approved}
POST /delegation/reject      X-API-Key, X-User-Email: <approver>
     {delegationId, approverEmail}                                 -> 201 {status: rejected}
```

`approverRole` / `approverLimit` must be the real values read from `/delegation/my-role`,
never hardcoded. Reject refuses those two properties. Implementation:
`spikes/armoriq/src/armoriq_spike/delegation.py`. Approver credentials stay in local `.env`,
never in CI.

## 4. Answers

| # | Question | Answer | Status | Evidence |
|---|---|---|---|---|
| Q1 | What does an uncovered tool do? | **Blocked**, `reason=no_matching_policy`, no policy named. Org setting Settings -> Policy Engine: mode Enforce, "When no policy matches: Block - refuse the call (default-deny)". Inside a policy the editor forces an action for every discovered tool, and untouched tools default to **Hold** (that is how `export_guest_list` was first held instead of blocked). A tool missing from the captured plan is blocked by the SDK before any HTTP (`tool-not-in-plan`). | CONFIRMED | `20261014T064334Z-probe-user.json` (no policy), `20261014T114949Z-uncovered.json` (`ghost_tool`), `20261014T141928Z-run.json` (the pre-fix first run, where BLOCK held) |
| Q2 | Does `for_user` need org-member emails? | **No for enforcement, yes for per-identity rules.** A non-member gets a signed plan and is governed by the policy's *clients* rule ("Govern hotel-mcp when called by clients", set to Anyone): ALLOW/HOLD/BLOCK all worked for `<guest>`, a non-member. *Member* rules only offer existing org members (no free-text email), so different policies per identity need invites. `resolve-user` for a non-member returns `isMember: false`, no policies, empty approver chain. | CONFIRMED | `20261014T114900Z-probe-user.json`, `20261014T074213Z-preflight.json` |
| Q3 | Which credentials does `POST /delegation/approve` accept? | **The org API key** (`X-API-Key`) plus `X-User-Email` naming the approver, body as in section 3. A non-member approver gets 403 "exceeds your approval limit of 0". The org_admin succeeded (201) only once `approverRole`/`approverLimit` from `/delegation/my-role` were sent; without them it also got "limit of 0". No dashboard JWT was needed or tested. | CONFIRMED | `20261014T150126Z`, `T150302Z`, `T150357Z`, `T151826Z`, `T152005Z-approve-test-api_key.json`, `T152400Z-reject-test.json` |
| Q3b | Does the backend verify the declared approver limit? | Approval succeeded only when the caller declared approverRole/approverLimit; omitting them gave limit 0. Possibly the backend trusts caller-declared limits. Not tested (a forged approval would breach hackathon rule 9), reported privately to ArmorIQ. | SUSPECTED, UNTESTED | as Q3 |
| Q4 | Does the execution report move the plan to `completed`? | **Yes.** In Intent: ALLOW plan `2fbbae05` = Completed; HOLD plan `0242f721` = Completed ("decided by" the admin); BLOCK plan `fb5debda` = Failed (blocked, never reported). | CONFIRMED (console) | `20261014T141928Z-run.json` (ALLOW, HOLD; its BLOCK case is the pre-fix hold), `20261014T142246Z-block-rerun.json` (the BLOCK proof); `docs/proof/armoriq-*.png` |
| Q5 | Does ArmorIQ contact the MCP URL in sdk mode? | **Not during enforcement.** During live probes and runs only our bridge (127.0.0.1, with bearer) called the toy server. ArmorIQ (`34.96.45.139`, UA `node`) called it only at registration: an unauthenticated connection test, an authenticated discovery (`initialize` + `tools/list`), and the security scanner. | CONFIRMED | `20261014-toy-server-inbound-registration.log` |
| Q6 | Registration needs | MCP: name `hotel-mcp`, URL with `/mcp`, auth Bearer = `MCP_BEARER_TOKEN`; result "Connected - 4 tools discovered". The **optional security scan fails** ("no candidate endpoint completed the MCP initialize handshake") because the scanner sends **no** Authorization header (tries `/mcp`, `/mcp/`, `/` -> 401/307/404). Agent: name `countersign`; the console requires an HTTPS agent URL, and registering it probes ~50 unauthenticated paths (`/openapi.json`, `/health`, `/version`, `/docs`...). | CONFIRMED | same log |
| Q7 | How the console labels sdk-mode plans | Every sdk-mode plan (allowed, held, blocked) is titled "csrg - <tool or decision>" with agent "csrg" and "No policy fired", although enforce returned `matched_policy=countersign-smoke` each time. `csrg` matches the IAP service name (`_build_env.py:26`). The BLOCK plan `fb5debda`'s Context tab even lists "AUTHORIZED: export_guest_list" (the plan step was signed at issuance) next to status Failed, which is misleading: the enforce response (`tool_denied`, in our evidence JSON) is the real proof of the block. | UNEXPLAINED (console display) | `docs/proof/armoriq-*.png`, `20261014T142246Z-block-rerun.json` |
| Q8 | Test keys (`ak_test_`) for CI? | The SDK accepts `ak_live_`, `ak_test_`, `ak_claw_` (`client.py:184-192`), but neither the docs nor the create-key form (Name, Expiration only) offers test keys; docs say "use API keys in CI and production". Not needed: CI never calls ArmorIQ (`live` tests are excluded from `check.py`). | UNKNOWN (not offered) | docs.armoriq.ai/platform/api-keys/create-key |
| Q9 | Do sdk-mode decisions show on tools.armoriq.ai? | **No.** Sessions, Intent Plans, Runs and Inbox were all empty; none of our plan ids, tools or names appear. All decisions are on platform.armoriq.ai (Intent / Plans, Held Actions). | CONFIRMED (console) | user check after run `20261014T141928Z` |

## 5. Live run summary (identity `<guest>`, policy `countersign-smoke`)

| Case | Tool | Decision | Outcome | Plan id | Reason |
|---|---|---|---|---|---|
| ALLOW | `get_hotel_info` | allow | ran, reported | `2fbbae05-af76-4b67-82b6-f28f21f207dc` | `enforcement_passed` |
| HOLD | `issue_refund` (250) | hold -> approved in console | ran, reported | `0242f721-2388-4a74-8a7e-b052f76d644c` | `rule_action_hold` |
| BLOCK | `export_guest_list` | block | never ran | `fb5debda-f313-4955-a8e3-f97a823f42af` | `tool_denied` |
| HOLD, API-approved | `issue_refund` (250) | hold -> approved over HTTP | ran, reported | `e8d7493b-4c11-475b-a057-a56519af495f` | `rule_action_hold` |
| HOLD, API-approved, non-blocking wait | `issue_refund` (250) | hold -> approved over HTTP, seen by `wait_for_approval` | ran, reported; expectations matched | `54cebc47-dd8c-4c43-9f26-025ea5973454` | `rule_action_hold` |

Console screenshots (platform.armoriq.ai -> Intent): `docs/proof/armoriq-allow.png` (Context
tab, plan `2fbbae05`), `docs/proof/armoriq-hold-approved.png` (Flow tab after approval,
"Completed by ... Approved by admin"), `docs/proof/armoriq-block.png` (Context tab, plan
`fb5debda`, status Failed; see Q7 for why its "AUTHORIZED" label is misleading). Plan ids are
not visible in the screenshots; the evidence JSON ties each decision to its plan id.

## 6. Consequences for Countersign

- **Bridge**: copy section 2 exactly; one session per call; declare only the tool calls the
  LLM chose this turn; fail closed.
- **Policy quota** is 2 policies / 5 members / 2 MCPs / 4 agents per org: keep one policy and
  register the real server under the same `hotel-mcp` name (change the URL only).
- **Identities**: the unverified/guest split needs member rules, which need invited members
  (the `+unverified`, `+guest`, `+manager` aliases = 4 of 5 slots with the owner), or a
  different differentiator. Decide before Day 2.
- **Money thresholds**: in sdk mode the backend decides; the console's amount-threshold
  setting for `issue_refund` (hold above $100) is still to be configured and tested.
- **hotel-mcp scan**: passes only if `initialize`/`tools/list` answer without auth; otherwise
  accept "Unscanned".
- **Agent server**: expose `/health` (and FastAPI's `/openapi.json`); the console probes them.
