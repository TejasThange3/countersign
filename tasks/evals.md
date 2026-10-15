# Lane: evals

TASK: Build the core of the evaluation harness:
- the 17 scenario files, their schema and the parser
- the approver module
- the metrics
- a text-mode runner

Audio simulation (ElevenLabs caller voices, noise, barge-in) is Day 3 work and comes after this
lane.

CONTEXT:
- AGENTS.md
- Scope section 5 (all of it) and the "Day 1 findings" section.
- contracts.py: the `GatewayFactory` and `ToolResult` shapes you consume.
- The proven approve and reject over HTTP. It uses the API key plus an X-User-Email header,
  with the role and limit read from GET /delegation/my-role. Two sources:
  - docs/research/armoriq-call-sequence.md section 3 (approver)
  - spikes/armoriq/src/armoriq_spike/delegation.py
- apps/mcp-server:
  - seed.py, which has the demo login LRK-1001/Okafor, the victim LRK-1002/Brandt, and the
    planted injection on LRK-1007
  - the `hotel-mcp reset --yes` command

FILES YOU OWN: evals/** (code, tests, scenarios, and its pyproject/uv.lock), and
notes-drafts/evals.md.

DO NOT TOUCH: apps/** and contracts.py.

DESIGN REQUIREMENTS:
1. The scenario YAML schema (pydantic) has these fields:
   - id, kind (legit or adversarial), persona, goal
   - caller turns, or an outline of them
   - the expected final DB state, as row-level assertions
   - the expected decision for each tool call (allow, hold or block)
   - the approver's action for each hold (approve or reject)
   - audio options for Day 3: voice id, noise SNR, barge-in
2. Write all 17 scenarios from scope section 5 (10 legit, plus adversarial A1-A7) using the real
   seed data. For A6 and A7, record the "if supported" outcomes honestly.
3. The approver module:
   - Port delegation.py.
   - Read the real role and limit from my-role; never hardcode them.
   - Pace calls to stay within the delegation rate limit of 30-60 per minute.
   - Credentials come from the local .env only, never from CI.
4. Metrics:
   - DB-state diff (no LLM judge)
   - decision accuracy
   - attack success
   - false positives
   - pass^k
   - ArmorIQ overhead vs approval wait
   - stubs for WER and latency, for Day 3
5. The text-mode runner:
   - Reset the DB.
   - Drive the conversation through the agent's text mode. Use the voice lane's HTTP endpoint
     once it's merged. Until then, use a driver at the `GatewayFactory` level that replays the
     scenario's scripted tool calls.
   - Collect the ToolResults and score them.
   - Write `evals/reports/<timestamp>.json` plus a Markdown table. Each report records
     armoriq_mode, the SDK version, the models, the approval mode and the plan ids.
   - Never fabricate a live result (product rule 5).

DONE MEANS:
- Parser and schema tests for all 17 files.
- Metrics tests with fixed inputs.
- Approver tests with a fake HTTP transport.
- An end-to-end runner test with a fake factory.
- `python scripts/check.py --changed` is green, the reviewer says PASS, and Codex says PASS
  (max 3 rounds).
- notes-drafts/evals.md is written in the AGENTS.md notes format.

Start by showing me your plan before editing.
