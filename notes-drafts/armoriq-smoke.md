## 15. ArmorIQ smoke test: allow, hold, block from Python

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

Glossary additions: *intent token*, *sdk mode*, *fail closed*, *delegation* (a held call
waiting for an approver), *clients rule* vs *member rule*, *cloudflared quick tunnel*.
