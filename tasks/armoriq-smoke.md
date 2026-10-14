# Lane: armoriq-smoke

TASK: De-risk ArmorIQ first, because it's the project's biggest unknown. Prove from Python, via
the core `armoriq-sdk` and `for_user` sessions, that one tool call is ALLOWED, one is HELD and
then approved, and one is BLOCKED, against a toy FastMCP tool. Write down the exact call
sequence the bridge must copy.

CONTEXT: scope sections 2 (the bridge lifecycle, identity mapping), 4 (policies, approvals),
8 (Day 1). Read the source of the Python Strands and LangChain integrations inside the installed
`armoriq-sdk` package before writing code, and copy their call order.

FILES YOU OWN:
- spikes/armoriq/** (its own uv project: toy server, smoke scripts, tests)
- docs/research/armoriq-call-sequence.md
- notes-drafts/armoriq-smoke.md

DO NOT TOUCH: everything else.

HUMAN STEPS (ask the user, then wait for confirmation; give them exact click paths):
- ArmorIQ API key in `.env` (`ARMORIQ_API_KEY`). Never print it.
- Register the toy MCP server (public URL via `cloudflared tunnel --url http://localhost:<port>`)
  and the agent in the ArmorIQ console, with names that match the code exactly.
- Create the service identities and a manager role; write the starting permissive policy, then
  the allow/hold/block rules.
- Approve the held call in the console (Plans -> Needs you) when the script waits.
- Take console screenshots of the allowed, held and blocked calls into docs/proof/ (insurance).

DONE MEANS:
- `spikes/armoriq/smoke.py` (marked/run as live) shows ALLOW, HOLD then approved, and BLOCK,
  printing the decision and plan id ArmorIQ returned for each.
- Recorded answers, each marked CONFIRMED by experiment or UNKNOWN: what an uncovered tool does;
  whether `for_user` requires org-member emails; which credentials `POST /delegation/approve`
  accepts; whether the execution report moves the plan to `completed`.
- docs/research/armoriq-call-sequence.md: the exact SDK call order for plan capture, intent
  token, invoke, hold wait/approval polling and execution report, with source file references.
- Unit tests for any helper code (mocks clearly named as fakes); `python scripts/check.py --changed`
  green, reviewer PASS, Codex review PASS (max 3 rounds).
- notes-drafts/armoriq-smoke.md written in the AGENTS.md notes format.

Start by showing me your plan before editing.
