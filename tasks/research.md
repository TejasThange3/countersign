# Lane: research (read-only)

TASK: Answer the Day 1 unknowns from the ArmorIQ docs and API reference, so the other lanes
don't have to guess. This lane writes no code.

CONTEXT: scope sections 2, 4 and 11 (reference links). Use the `researcher` subagent approach:
primary sources only, every claim with a URL.

FILES YOU OWN:
- docs/research/armoriq-day1-unknowns.md
- notes-drafts/research.md

DO NOT TOUCH: everything else.

QUESTIONS (answer each as CONFIRMED / DOCS DISAGREE / UNKNOWN + experiment to settle it):
1. Default behaviour for a tool call no policy covers: `no_matching_policy` refusal or allow?
2. Does `for_user(email)` accept non-org-member emails? What policy/limits apply then?
3. Delegation API (`GET /delegation/poll`, `POST /delegation/approve|reject`): which auth does an
   approver use (API key vs dashboard JWT)? Rate limits?
4. Do policies support amount thresholds (allow up to $100, hold above) on fields named `amount`?
   Exact field names recognised.
5. Rate limiting per identity (for `verify_guest` brute force) and velocity limits (many small
   refunds): supported? How configured?
6. How plan extension works when the LLM adds tool calls mid-conversation (signed delta, one token
   per call session).
7. Role ranking for approvers: how a role is made "higher" than another.
8. Hackathon account: are policies, holds, delegation API and observability available at no cost?

DONE MEANS:
- docs/research/armoriq-day1-unknowns.md answers all 8, each with source links.
- A short "Implications for the bridge" section at the end.
- notes-drafts/research.md written in the AGENTS.md notes format.
- No code changes, so the Stop gate passes instantly and no Codex review is needed.

Start by showing me your plan before researching.
