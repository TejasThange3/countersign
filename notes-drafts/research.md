## N. ArmorIQ research: which console, and how the guard really behaves

**Analogy.** A hotel chain has two security offices.

- **The "house rules" office (tools.armoriq.ai).** It writes a rulebook for the cleaning robots
  that work inside staff laptops: "don't open the safe drawer", "ask before using the shredder".
  Each robot carries its own copy and checks it before acting.
- **The front gate office (platform.armoriq.ai).** It writes the rulebook that the gate guard
  checks for every request coming from the front desk: "refunds over $100 need a manager".

Our front desk agent only ever talks to the gate guard. A rule written in the house-rules office
never reaches the gate. It looks like the house-rules office may even be running in a practice
building (staging) instead of headquarters (production).

When the gate guard says "wait for a manager", it hands back a ticket number. The desk keeps
checking the ticket. Only a *more senior* manager, never the person who asked, can stamp it
approved.

**Technical explanation.** This lane wrote no code. It answered the 11 Day 1 unknowns from
primary sources only:

- the docs (`docs.armoriq.ai/llms-full.txt`, the whole docs site in one text file);
- the `armoriq-sdk` 0.6.10 Python wheel, read without installing it;
- the JavaScript the two consoles ship to the browser.

The key findings:

- **Two "Policy Studio"s.**
  - The one on tools.armoriq.ai publishes an `armor.policy.v1` *plugin profile*. A **plugin
    profile** is a rule set that the ArmorClaude plugin pulls and enforces locally, inside Claude
    Code.
  - The SDK's enforcement call, `POST /iap/sdk/enforce` (the gate guard), checks *server-side
    `Policy` documents*. Those are made on platform.armoriq.ai. A **`Policy` document** is
    ArmorIQ's server rule with `memberRules`, `amountThreshold` and a
    `defaultEnforcementAction`.
  - The docs state the two are separate.
- **Two environments.**
  - The tools.armoriq.ai bundle talks to `staging-api.armoriq.io`.
  - The SDK and platform.armoriq.ai talk to `api.armoriq.ai`, which is production.
  - That is strong evidence, not proof. A 10-minute login experiment settles it.
- **Holds (the wait-for-a-manager ticket).**
  - A held call returns a `delegation_id`, the ticket number.
  - The SDK only *polls* `/delegation/{id}/status`. There is no webhook.
  - The SDK has no approve call. The dashboard approves by posting
    `/iap/plan/{planId}/update-status` with a logged-in user's JWT, a **JSON Web Token**: the
    signed login token a browser sends as `Authorization: Bearer ...`.
  - The approver must have a higher-ranked role than the requester, and can never approve their
    own request.
- **Plans can't be extended.**
  - An **intent plan** is the list of tools the agent declares up front, signed into a token.
  - Adding a tool means a brand-new plan and token, and any pending approval is lost. So the
    bridge declares every hotel tool once per call.
- **Money rules.**
  - The SDK reads the argument `amount`.
  - `requireApprovalAbove` only holds a call when it is paired with `enforcementAction: hold`.
- **Unknowns left open.** The default for uncovered tools is contradicted between docs pages,
  so we bind one explicit policy with an explicit default. The rest are listed with experiments.

The gate guard in the analogy is `/iap/sdk/enforce`. The house-rules office is
tools.armoriq.ai's Policy Studio. The ticket is `delegation_id`, and the senior manager is the
higher-ranked approver account.

**Where it lives.** `docs/research/armoriq-day1-unknowns.md`. It has every answer with source
links and SDK line numbers, plus an "Implications for the bridge" list at the end.

**How to check it works.**

- Open the doc. Every claim has a URL or an `armoriq_sdk/<file>.py:<line>` reference.
- To confirm the environment finding yourself, create an API key on each console and run:
  ```
  curl -H "X-API-Key: $KEY" https://api.armoriq.ai/iap/sdk/orgs
  curl -H "X-API-Key: $KEY" https://staging-api.armoriq.ai/iap/sdk/orgs
  ```
  A 200 on one and a 401 on the other shows which environment that key belongs to.
