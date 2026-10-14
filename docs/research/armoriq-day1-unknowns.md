# ArmorIQ Day 1 unknowns

Research lane, 2026-10-14. Primary sources only:

- **Docs:** docs.armoriq.ai. The full corpus was read from `https://docs.armoriq.ai/llms-full.txt`.
  Page URLs are cited below.
- **SDK:** the `armoriq-sdk` 0.6.10 wheel from PyPI, read but not installed. Paths like
  `session.py:813` are inside `armoriq_sdk/`.
- **Consoles:** the public JavaScript bundles served by tools.armoriq.ai and platform.armoriq.ai,
  fetched 2026-10-14.

No live ArmorIQ calls were made. Each "Experiment" below is meant for the armoriq-smoke lane or for
a human with a console login.

Verdicts:

- **CONFIRMED:** a primary source states it.
- **DOCS DISAGREE:** two primary sources conflict.
- **UNKNOWN:** not answerable from public sources. Each one comes with an experiment.

Already established by the armoriq-smoke lane (SDK 0.6.10 read), and not repeated here:

- The SDK talks only to `api.armoriq.ai`, `iap.armoriq.ai` and `proxy.armoriq.ai`.
- Its error messages point to `platform.armoriq.ai/dashboard/api-keys`.
- It never mentions tools.armoriq.ai.

---

## Part 1: which console (Q9-Q11)

### Summary for the other lanes

1. **The SDK is enforced by server-side policies.** These are created on platform.armoriq.ai in
   Policies, Policy Builder, or *its* Policy Studio at `/dashboard/policy-studio`.
2. **tools.armoriq.ai's Policy Studio is a different object.** It publishes an `armor.policy.v1`
   *plugin profile* that the ArmorClaude and ArmorCodex plugins enforce locally on a developer's
   machine. The docs say outright that it does not change server-side policies. It does **not**
   govern our agent's `/iap/sdk/enforce` calls.
3. **The two consoles look like different environments today.**
   - The deployed tools.armoriq.ai bundle signs in against `https://staging-api.armoriq.io`.
   - platform.armoriq.ai and the SDK use production `https://api.armoriq.ai`.
   - If that holds, an SDK run with a production key will not show up in tools.armoriq.ai, and a
     key made on tools.armoriq.ai will not work with the SDK's default endpoint.
   - This is strong evidence, not proof. The experiment E1-E4 settles it in about 10 minutes and
     needs a login.
4. **Ask the organizers which they mean.** "Judges want tools.armoriq.ai and Policy Studio" may
   mean the platform's Policy Studio, or that they expect SDK traffic to show up in
   tools.armoriq.ai. Ask them before building the demo around either console.

### Q9. Are the two consoles the same backend and account? Which issues keys, registers agents and MCP servers, and holds the policies the SDK enforces?

**Verdict: DOCS DISAGREE / UNKNOWN on whether they share an environment. CONFIRMED that the two
Policy Studios are different objects.**

**What each console is, per the docs:**

| | tools.armoriq.ai ("ArmorIQ Tools") | platform.armoriq.ai ("the Platform") |
|---|---|---|
| Audience | People using Claude Code or Codex. "It fits if you use Claude Code or OpenAI Codex" ([/tools](https://docs.armoriq.ai/tools)) | Teams running agents through the SDK, MCP servers and IAP ([/platform](https://docs.armoriq.ai/platform)) |
| Tenancy | "One account, one workspace, one person"; no invites ([/tools/limits](https://docs.armoriq.ai/tools/limits)) | Organizations with members, roles and quotas ([/platform/organizations](https://docs.armoriq.ai/platform/organizations)) |
| "Policy Studio" | Authors the **plugin profile**: per-tool allow/hold/block, one folder lock, and a default for unmatched tools ([/tools/policy-studio](https://docs.armoriq.ai/tools/policy-studio)) | Authors **server-side `Policy` documents** with metadata, scheduling, member rules and client rules. Lives at `/dashboard/policy-studio` ([/platform/policy-studio](https://docs.armoriq.ai/platform/policy-studio), [/platform/policy-studio/single-policy](https://docs.armoriq.ai/platform/policy-studio/single-policy)) |
| Held actions | "You cannot approve or dismiss a held action here yet" ([/tools/console#inbox](https://docs.armoriq.ai/tools/console)) | Delegation approve/reject API exists ([/platform/api-reference](https://docs.armoriq.ai/platform/api-reference)) |
| Backend in deployed bundle | `ia="https://staging-api.armoriq.io"`, used for `/auth/login`, `/auth/me` and `/auth/refresh` (`tools.armoriq.ai/assets/index-DLGPl4Nu.js`) | `VITE_BACKEND_URL:"https://api.armoriq.ai"` (`platform.armoriq.ai/assets/index-BUsVvuj6.js`) |

**The two Policy Studios are different enforcement points (CONFIRMED).**

- [/tools/enforcement](https://docs.armoriq.ai/tools/enforcement), "Two enforcement points":
  > "**The plugin on your machine** enforces the profile you publish from Policy Studio. [...]
  > **The server** holds policies that apply to agents and MCP servers, listed on the Policies
  > screen [...]. They are separate. Publishing a profile in Policy Studio does not change a
  > server-side policy"
- [/tools/policy-studio](https://docs.armoriq.ai/tools/policy-studio):
  > "It publishes a policy profile that the ArmorClaude plugin enforces locally."
  > "A policy listed there is not the same object as a tool rule in Policy Studio"
- SDK `cli_policy.py:1-20`:
  > "this manages the org-scoped policy profile held by the control plane, the one the dashboard
  > edits and agent plugins pull. It is NOT the `policy:` allow/deny block in armoriq.yaml"

  Its routes are `/policies/profiles/{active,draft,propose,template}` and `/policies/sync`.
- These are exactly the routes compiled into the tools.armoriq.ai bundle: `/policies/profiles/confirm`,
  `/draft`, `/propose` and `/template`.

**What `/iap/sdk/enforce` evaluates (CONFIRMED that it is server-side; INFERRED that it uses
`Policy` docs and not the profile).**

- `session.py:811-833` posts `tool`, `arguments`, `intent_token`, `policy_snapshot`,
  `user_email` and `agent_id` to `{backend}/iap/sdk/enforce`.
- It reads `allowed`, `enforcementAction`, `matchedPolicy.name` and `obligations` from the response.
- Nothing in the SDK's enforce path fetches `/policies/profiles/*`. Only the CLI and the plugins do.
- The platform docs place enforcement on "policies bound to specific targets (MCP servers or
  agents)" ([/platform/policies/enforcement](https://docs.armoriq.ai/platform/policies/enforcement)).
- The ArmorPay docs say all of its studio output "compile[s] to a standard `Policy` kind YAML
  document", the "same `Policy` document every ArmorIQ product targets"
  ([/armorpay/concepts](https://docs.armoriq.ai/armorpay/concepts)).
- So policies made in **tools.armoriq.ai's Policy Studio are not what `/iap/sdk/enforce` checks**.
  Policies made in **platform.armoriq.ai's Policies or Policy Studio are**.
- Not stated anywhere: whether the server also consults the org's active plugin profile. That one
  is inferred; experiment E4 settles it.

**Same backend? Same account? (Evidence conflicts.)**

For a shared identity and account:

- One credentials file, `~/.armoriq/credentials.json`, is "Shared with the `armoriq` CLI and every
  other Armor\* product" (ArmorGemini docs, "Where policies live" table,
  [/armorgemini/getting-started/policies](https://docs.armoriq.ai/armorgemini/getting-started/policies)).
- The ArmorClaw installer approves the device at `platform.armoriq.ai/auth/device`. If that fails,
  it "falls back to the dashboard at tools.armoriq.ai/tools/api-keys and accepts a pasted key"
  ([/armorclaw/installation/quickstart](https://docs.armoriq.ai/armorclaw/installation/quickstart)). The docs treat a key from either
  console as interchangeable.
- The tools.armoriq.ai Policies screen "lists server-side policies that apply to agents and MCP
  servers" ([/tools/console](https://docs.armoriq.ai/tools/console)). Those are the same kind of
  object the platform manages, and the same statuses (active, draft, shadow, inactive, expired) and
  actions (block, hold, allow and log, alert, quarantine) appear in both sets of docs.

Against (different environments today):

- The production tools.armoriq.ai bundle hardcodes `https://staging-api.armoriq.io` as its auth
  and API base.
- DNS on 2026-10-14:

  | Host | IP |
  |---|---|
  | `staging-api.armoriq.io` | 136.81.122.75 |
  | `staging-api.armoriq.ai` | 136.81.122.75 |
  | `api.armoriq.ai` | 34.54.2.114 |

- The SDK's endpoint table maps `staging-api.armoriq.ai` to "conmap-auto-staging" and
  `api.armoriq.ai` to "conmap-auto" (`_build_env.py:22-31`).
- The docs warn that keys are per-environment: "Your ArmorIQ API key is from the wrong env. The SDK
  is staging-flavored (sdk-dev) but you logged in against prod (`platform.armoriq.ai`)"
  ([/armorcopilot/troubleshooting](https://docs.armoriq.ai/armorcopilot/troubleshooting)).
- A shared IP is consistent with one staging load balancer serving both hostnames. It does not
  prove one database, so this is evidence, not proof.

**Which console does what, for the SDK (CONFIRMED from docs plus SDK):**

- **SDK API key:** platform.armoriq.ai → Settings → API Keys.
  - The SDK error text: `client.py:181,192,483`.
  - The docs: "From platform.armoriq.ai → Settings → API Keys"
    ([/cookbook](https://docs.armoriq.ai/cookbook), "Build a Google ADK Agent with the ArmorIQ SDK").
  - tools.armoriq.ai can also create keys scoped to "All products, ArmorClaude, ArmorCodex, or
    ArmorCopilot" ([/tools/api-keys](https://docs.armoriq.ai/tools/api-keys)). Those may be staging
    keys; see E2.
- **Agent and MCP registration:**
  - Backend routes: `POST /agent/register` and `POST /mcp/register` on the platform API
    ([/platform/api-reference](https://docs.armoriq.ai/platform/api-reference)).
  - tools.armoriq.ai also has `/agents` and `/mcp-servers` screens
    ([/tools/console](https://docs.armoriq.ai/tools/console)), but those go to whatever backend that
    bundle points at.
- **Policies the SDK enforces:** server-side `Policy` documents. platform.armoriq.ai authors them
  in Policies, Policy Builder or `/dashboard/policy-studio`, and tools.armoriq.ai *lists* them on
  its Policies screen.

**Experiment to settle it (about 10 minutes, needs a login):**

- **E1, same account?** Sign in to both consoles with the same Google account. Compare the
  workspace or org name and the API key list. If a key created on one appears on the other, they
  share a database.
- **E2, which environment does a key belong to?** Create a key on tools.armoriq.ai, then run:
  ```
  curl -H "X-API-Key: $K" https://api.armoriq.ai/iap/sdk/orgs
  curl -H "X-API-Key: $K" https://staging-api.armoriq.ai/iap/sdk/orgs
  ```
  The route comes from SDK `cli.py:535`. A 200 on one and a 401 on the other gives the
  environment. Repeat with a key from platform.armoriq.ai.
- **E3, does SDK activity show on tools.armoriq.ai?** Run the armoriq-smoke script with the
  platform key, then look for the session on tools.armoriq.ai in Sessions, Runs and Intent Plans.
- **E4, which policies does `/iap/sdk/enforce` obey?**
  1. On tools.armoriq.ai Policy Studio, publish a profile with the smoke tool set to **Block**.
     Run the smoke call. If it is still allowed, the profile is not consulted by the SDK.
  2. Then create a block policy on platform.armoriq.ai for the same tool. Run it again and expect
     `matchedPolicy.name` to be that policy.

**If E2 shows tools.armoriq.ai is staging:**

- The SDK can be pointed there with `ARMORIQ_ENV=staging`, or with
  `BACKEND_ENDPOINT=https://staging-api.armoriq.ai` (`_build_env.py:11-16`, `client.py:165-168`).
- That trades production stability for the console the judges want. Decide it with the organizers;
  don't decide it silently.

### Q10. Where does the `armoriq-sdk` client report decisions, and what is its default base URL?

**Verdict: CONFIRMED.**

The default environment is `production` (`_build_env.py:20`). The defaults are:

| Endpoint | Host | Source |
|---|---|---|
| backend | `https://api.armoriq.ai` | `_build_env.py:36` and `client.py:89` |
| IAP | `https://iap.armoriq.ai` | `client.py:87` |
| proxy | `https://proxy.armoriq.ai` | `client.py:88` |

- **Decisions:** `POST {backend}/iap/sdk/enforce` (`session.py:813`).
- **Telemetry:** the observability shipper posts to `{endpoint}/observability/spans`
  (`observability/shipper.py:52,198`), the ingest route of the same backend, "conmap-auto"
  (`observability/schema.py:6`).

The base URL can be overridden in either of these ways (`client.py:121-168`, `_build_env.py:52-56`):

- `ARMORIQ_ENV=staging|local|production`, or
- the per-endpoint variables `BACKEND_ENDPOINT`, `IAP_ENDPOINT` and `PROXY_ENDPOINT`. These win
  over `ARMORIQ_ENV`.

So the SDK reports to the production backend that platform.armoriq.ai reads. Whether
tools.armoriq.ai shows that data depends on Q9 (E2/E3). Its deployed bundle reads
`staging-api.armoriq.io`.

### Q11. Is "ArmorClaude" (the curl installer on tools.armoriq.ai Home) unrelated to governing our product agent?

**Verdict: CONFIRMED that it is unrelated. Skip it for the product.**

- The docs index describes it as a "Claude Code extension that enforces security policies on Claude
  Desktop and CLI agents" ([docs.armoriq.ai](https://docs.armoriq.ai),
  [/armorclaude](https://docs.armoriq.ai/armorclaude)).
- The installer, `curl -fsSL https://armoriq.ai/install_armorclaude.sh | bash`, "installs the
  plugin into your assistant, plus the small `armoriq` CLI"
  ([/tools/quickstart](https://docs.armoriq.ai/tools/quickstart)).
- It sees "the tool calls your assistant attempts" (`Read`, `Bash`, `Edit` and similar) and applies
  the Policy Studio profile locally ([/tools/architecture](https://docs.armoriq.ai/tools/architecture),
  [/tools/policy-studio](https://docs.armoriq.ai/tools/policy-studio)).
- It governs Claude Code on a developer's machine. It does not govern a Pipecat or Python agent
  calling `hotel-mcp`.
- The only overlap: if a teammate installs it, the Claude Code sessions that *build* Countersign
  would show up in tools.armoriq.ai. That could be an optional extra for the demo, but it is not
  proof that ArmorIQ governs the product.

---

## Part 2: policy semantics, identity, delegation (Q1-Q8)

### Q1. Default for a tool call no policy covers

**Verdict: DOCS DISAGREE.**

Platform docs say allow:

- [/platform/policies/enforcement](https://docs.armoriq.ai/platform/policies/enforcement):
  > "If no policy matches, access is **allowed by default**"
  > "Resources without an assigned policy allow access based on organization membership, and an
  > assigned policy with no matching rule also allows by default."

Policy-kind docs say block:

- [/armorpay/concepts](https://docs.armoriq.ai/armorpay/concepts), resolution order:
  > "1. `toolEnforcement[toolName]` 2. `rule.enforcementAction` 3.
  > `policy.spec.defaultEnforcementAction` 4. `block` (fail-closed default when nothing else
  > matches)"
- The same order appears for ArmorHealth.
- Tools outside `allowedTools` "fall through to the policy's fail-closed default".
- `defaultEnforcementAction` is configurable per policy:
  `block | hold | allow_log | alert | quarantine`
  ([/armorpay/policy-studio](https://docs.armoriq.ai/armorpay/policy-studio)).

What the SDK does:

- A failed enforce call blocks: `enforce-unavailable: <err>` (`session.py:860-864`).
- A tool missing from the captured plan is blocked client-side before the server is asked:
  `tool-not-in-plan` (`session.py:804-809`).
- The string `no_matching_policy` does not appear anywhere in the SDK. The server's reason codes
  for an uncovered tool are undocumented. The API reference points to Swagger at `/api-docs`,
  "available outside production" ([/platform/api-reference](https://docs.armoriq.ai/platform/api-reference)).

Reconciling the two: a resource with *no policy bound* is likely allowed, while inside a bound
policy, a tool missing from `allowedTools` hits `defaultEnforcementAction`, with `block` as the
fallback. This is inference.

**Experiment:**

1. With no policy bound to the agent, call an uncovered tool and record `allowed`,
   `enforcementAction` and `reason`.
2. Bind a policy with `allowedTools: [verify_guest]` and `defaultEnforcementAction: block`, then
   call `create_booking`.
3. Repeat with `defaultEnforcementAction: allow_log`.

**For the bridge:** always bind an explicit policy with an explicit `defaultEnforcementAction`.
Never rely on the unbound default.

### Q2. Does `for_user(email)` accept non-org-member emails?

**Verdict: CONFIRMED that the SDK does no check. UNKNOWN what the server does.**

- `for_user` only builds a local scope object (`client.py:374-388`, `client.py:1813-1815`). There is
  no network call and no validation.
- The email is sent later:
  - as `user_email` on intent-token mint (`client.py:593-601`);
  - as `user_email` on `/iap/sdk/enforce` (`session.py:819`);
  - as `X-User-Email` on `GET /delegation/my-role` when a call is held (`client.py:1514-1540`).
- If the role lookup fails, the SDK falls back to the least-privileged role: "defaulting to
  least-privileged role (agent_user, limit 0)".
- Membership is resolved only by an explicit `resolve_user()`: `POST {backend}/iap/sdk/resolve-user`
  with `{"userEmail": ...}`, which raises `ConfigurationException` on HTTP >= 400
  (`client.py:341-367`).
- The docs are silent on non-members.
  [/platform/policies/enforcement](https://docs.armoriq.ai/platform/policies/enforcement) only says
  unbound resources "allow access based on organization membership".

**Experiment:**

1. Call `resolve_user("guest-0001@countersign.test")` and record the status and body.
2. Run `for_user(...)` with the same email, then `check()` three calls: an uncovered tool, a refund
   over the threshold, and a blocked tool. Compare each with a real member's email.

**For the bridge:** be ready for guests to need a fixed service identity in `for_user`, with the
guest id carried only as an injected tool argument.

### Q3. Delegation API: endpoints, approver auth, rate limits

**Verdict:**

- **Agent side: CONFIRMED** from the SDK.
- **Dashboard approve path: CONFIRMED** from the platform console bundle.
- **API-key approve and reject: UNKNOWN.** The routes exist, but their body and auth are
  undocumented.

The SDK (0.6.10) has **no approve or reject call**, so approval is raw HTTP. All routes below are on
the backend `https://api.armoriq.ai`, with no `/api` or `/v1` prefix (`client.py:89`).

**Auth modes** ([/platform/api-reference](https://docs.armoriq.ai/platform/api-reference)):

- `Authorization: Bearer <jwt>` is for dashboard and user calls.
- `x-api-key: <key>` is for SDK, agent and plugin calls.
- "A few routes accept both."
- The page does not say which mode each delegation route takes.

**Agent side: what the SDK calls when a call is held.** All are `client.py` lines.

| Method and path | Headers | Body / query | Response used | Line |
|---|---|---|---|---|
| `GET /delegation/my-role` | `X-API-Key`, `X-User-Email` | none | `{role, limit}`; on failure, falls back to `agent_user` with limit 0 | 1518 |
| `POST /delegation/request` | `X-API-Key`, `X-User-Email`, `Idempotency-Key` | camelCase JSON: `tool, action, arguments, amount, requesterEmail, requesterRole, requesterLimit, domain, targetUrl, planId, intentReference, merkleRoot, reason` (`models.py:192-209`) | `{delegationId, status, expiresAt}` | 1551 |
| `GET /delegation/check-approved` | `X-API-Key`, `X-User-Email` | `?tool&amount&planId` | `{approved, delegationId, ...}` | 1583 |
| `GET /delegation/{delegationId}/status` | `X-API-Key` | none | `{status}`: `pending`, `approved`, `rejected`, `expired` or `none` | 1605 |
| `POST /delegation/mark-executed` | `X-API-Key`, `X-User-Email`, `Idempotency-Key` | `{delegationId, planId?}` | none | 1632 |

What the SDK does with a hold:

- **Return value.** The session path (`enforce_sdk` and `dispatch`) does not raise. It returns
  `EnforceResult(action="hold", allowed=False, delegation_id=..., reason=...)`
  (`session.py:1285-1292`).
- If creating the delegation fails, `delegation_id` is `None` and the call stays blocked
  (`session.py:1253-1258`).
- **Exceptions on the low-level path.** `client.invoke()` raises `PolicyHoldException`
  (`client.py:942`) and `PolicyBlockedException` (`client.py:936`).
- **Waiting is polling only; there is no webhook.**
  - `await ArmorIQSession.await_approval(delegation_id, timeout=300.0, interval=5.0)` polls
    `/delegation/{id}/status` (`session.py:1294`).
  - It returns `"approved"`, `"rejected"` or `"timeout"` and marks approved delegations executed.
  - It treats HTTP 429, 502, 503 and 504 as transient.
- **Avoid `invoke_with_policy(wait_for_approval=True)`.** It polls with blocking `time.sleep`
  (`client.py:1754`), which would stall the Pipecat event loop.
- **Local mode turns holds into blocks** with "switch ARMORIQ_MODE=proxy to enable approval
  workflows" (`session.py:1048-1055`).

**Approver side, path A: the dashboard (CONFIRMED from `platform.armoriq.ai` JS chunks,
2026-10-14).**

- The Plans and Held-actions screens approve by changing the *plan's* status. They do not call
  `/delegation/approve`:
  ```
  POST https://api.armoriq.ai/iap/plan/{planId}/update-status
  Authorization: Bearer <dashboard JWT>      # from localStorage, set by POST /auth/login
  x-organization-id: <orgId>
  {"status": "approved" | "blocked" | "held", "decisionNote": "<optional>"}
  ```
- The held-actions mutation maps reject to `"blocked"`: `cs={approved:"approved",rejected:"blocked"}`.
- The docs describe this as one of "two independent paths that can approve or reject a plan: the
  SDK-facing delegation API, and the dashboard's admin status-update action"
  ([/platform/plans](https://docs.armoriq.ai/platform/plans)).

**Approver side, path B: the delegation API (UNKNOWN beyond the route names).**

- The docs list `GET /delegation/poll`, `POST /delegation/approve` and `POST /delegation/reject`
  ([/platform/api-reference](https://docs.armoriq.ai/platform/api-reference)).
- No body, response or auth mode is documented.
- The SDK never calls `/delegation/poll`. It is probably the approver's pending list.
- Swagger (`/api-docs`) is "available outside production". `api.armoriq.ai/api-docs` returns 404.
- No `github.com/armoriq` repo contains these routes. The backend is not open source.

**Rate limits:**

- The `delegation` bucket is 30-60 requests/min, covering "Delegation create/approve/reject".
- The `auth` bucket (login) is 5-10/min. Reuse one approver JWT rather than logging in per hold.
- "Most endpoints are unthrottled", including, presumably, status polling.
- Source: [/platform/api-reference](https://docs.armoriq.ai/platform/api-reference).

**Other facts:**

- Unapproved delegations expire after `DELEGATION_EXPIRY_SECONDS`, default 3600
  ([/platform/self-hosting](https://docs.armoriq.ai/platform/self-hosting)).
- The docs say SDK `delegate()` posts `/delegation/create`. The SDK says "The /delegation/create
  route was removed; the live delegation endpoint is /iap/trust/delegate" (`client.py:1024-1026`).
  **DOCS DISAGREE.** That is agent-to-agent delegation, not approval, so it doesn't matter to us.

**Experiment:**

1. Trigger a hold with the smoke script and note `delegation_id` and `planId`.
2. As a second, higher-role user, call `POST /iap/plan/{planId}/update-status` with
   `{"status":"approved"}` using that user's JWT.
3. Check whether `GET /delegation/{id}/status` flips to `approved`. That tells us whether path A
   satisfies `await_approval`.
4. Separately, `POST /delegation/approve` with `{"delegationId": ...}`, once with `x-api-key` and
   once with the Bearer JWT. Read the 4xx error text for the expected fields.
5. In both cases, also capture the browser DevTools request when approving from the dashboard UI.

### Q4. Amount thresholds on a field named `amount`

**Verdict: CONFIRMED that fields exist. DOCS DISAGREE (silent vs SDK) on units. A hold needs an
explicit action.**

- **Fields**, under `spec.memberRules.<email or "*">`
  ([/armorpay/concepts](https://docs.armoriq.ai/armorpay/concepts)):
  - `amountThreshold.maxPerTransaction`
  - `amountThreshold.requireApprovalAbove`
  - `amountThreshold.currency`
- **The threshold alone does not hold.** "`amountThreshold.requireApprovalAbove` only *describes* a
  number - it does not by itself set the enforcement action. The rule also needs
  `enforcementAction: hold` (or a `toolEnforcement` entry)"
  ([/armorpay/troubleshooting](https://docs.armoriq.ai/armorpay/troubleshooting)).
- **Which argument is the amount.**
  - From the MCP tool metadata `amountFields`, `amountUnit` and `isFinancial` (`models.py:133-140`).
  - Otherwise the keys `amount`, `value`, `total`, `price` and `cost`, in that order
    (`session.py:1340-1349`).
  - So `amount` is recognised (AGENTS.md rule 4 holds).
- **Units.** The docs pair thresholds only with `currency`. The SDK divides by 100 only when
  `amountUnit == "cents"` (`client.py:1493`, `session.py:1368`).
- **Comparison.** The SDK's local evaluator uses strict `>` (`session.py:1373-1402`). Server-side
  inclusivity is undocumented.

**Experiment:** register `amountFields: ["amount"]` with no `amountUnit`, set
`requireApprovalAbove: 100` and `enforcementAction: hold`, then call with amounts 100, 100.01 and
10000.

### Q5. Per-identity rate limits and velocity limits

**Verdict: velocity is CONFIRMED as policy fields (behaviour untested). Per-identity rate limiting
is UNKNOWN.**

- **Velocity fields:** `velocityLimit.maxTransactionsPerHour` and
  `velocityLimit.maxCumulativePerDay` under `memberRules`
  ([/armorpay/concepts](https://docs.armoriq.ai/armorpay/concepts)).
  - Like thresholds, they "don't set the enforcement action directly".
  - The docs don't say whether counting is per member, agent or org.
  - It is not implemented in the SDK, so it is server-side only.
- **Rate limits:**
  - Older policy docs list `rate_limit` ("Max requests per hour") as a policy field
    ([/sdk/concepts/policy-management](https://docs.armoriq.ai/sdk/concepts/policy-management)).
  - Platform Policy Studio has only a "Global requests-per-hour limit".
  - Nothing documents a per-tool, per-identity attempt limit, e.g. for `verify_guest`.
- **Platform API limits:** "most endpoints are unthrottled". Only `auth` (5-10/min) and
  `delegation` (30-60/min) are throttled
  ([/platform/api-reference](https://docs.armoriq.ai/platform/api-reference)).

**Experiment:**

1. Set `maxTransactionsPerHour: 3` with `enforcementAction: hold`, make 4 refunds as one identity,
   then repeat as another identity. This shows whether counting is per identity.
2. Set the Policy Studio rate limit low and call `verify_guest` 20 times a minute.

**For the bridge:** count `verify_guest` failures per caller in the bridge, which owns identity.
Don't rely on ArmorIQ for brute-force protection.

### Q6. Plan extension mid-conversation

**Verdict: CONFIRMED that there is no signed-delta or extension mechanism. Adding tools means a
new plan and a new token.**

- **Plans are immutable.** The docs say plans "Cannot be changed once signed"
  ([/sdk/concepts/intent-plans](https://docs.armoriq.ai/sdk/concepts/intent-plans)). To add an
  action, call `capture_plan` again and then `get_intent_token`
  ([/sdk/concepts/token-lifecycle](https://docs.armoriq.ai/sdk/concepts/token-lifecycle)).
- **What happens to a tool that isn't in the plan.**
  - Session path: blocked client-side with `tool-not-in-plan` (`session.py:804-809`).
  - `client.invoke`: raises `IntentMismatchException` before any network call
    (`client.py:803-818`). The proxy's HTTP 409 maps to the same exception (`client.py:974-980`).
- **How `session.start_plan(tool_calls)` behaves** (`session.py:393-490`):
  - It hashes the tool-call list. If the hash is unchanged, it reuses the cached token.
  - Otherwise it **clears** `_declared_tools`, captures a new plan and mints a new token. Earlier
    tools are not merged in.
  - Each plan is its own trace and its own plan row.
  - Approvals are plan-scoped ("An approval is a decision about one plan", `client.py:1573-1578`),
    so **an approval does not survive a re-plan**.
- **Token validity.** The session default is 3600 s (`session.py:119`). Low-level
  `get_intent_token` defaults to 60 s (`client.py:584`). An expired token raises
  `TokenExpiredException` client-side (`client.py:739-744`).
- **One token per session.** The SDK keeps one `_current_token` per session object.
- **Backend: UNKNOWN.** Whether superseded plans are closed, and whether any concurrency limit
  applies, is not documented.

**Experiment:**

1. `start_plan([A])`, then `dispatch(B)`. Expect `tool-not-in-plan`.
2. `start_plan([A, B])`, then `dispatch(B)`.
3. Check the dashboard for a second plan row and the status of the first.

### Q7. Role ranking for approvers

**Verdict: CONFIRMED that a ranking exists and self-approval is banned. UNKNOWN how roles are
ordered and where an approver role is configured.**

- **The rule** ([/platform/plans](https://docs.armoriq.ai/platform/plans)):
  > "If the request exceeds the requester's role limit, a delegation request is created and the
  > plan is held."
  > "A human with a **higher-ranked role** than the requester can approve or reject the request. A
  > requester can never approve their own request."
- `ALLOW_SELF_APPROVAL` (default `false`) relaxes this only on the dashboard path
  ([/platform/self-hosting](https://docs.armoriq.ai/platform/self-hosting)).
- **Role and limit come from `GET /delegation/my-role`** as `{role, limit}`, with a fallback to
  `agent_user` and limit 0 (`client.py:1515-1545`).
  - On the session path, the SDK hardcodes `requester_role="agent_user"` and `requester_limit=0`
    (`session.py:1270`).
  - `agent_user` is not one of the org roles.
- **The org roles are a different set.** They are Organization Admin, IAM Admin, Developer, Analyst
  and Viewer ([/platform/organizations/roles-quotas](https://docs.armoriq.ai/platform/organizations/roles-quotas)).
  No ranking is given there.
- **Delegation roles look domain-level.** The SDK maps an org role to a domain role through the MCP
  tool metadata `role_mapping` (`client.py:1508-1511`).
- **An approver chain exists server-side.** `POST /iap/sdk/resolve-user` returns
  "membership + policies + approver chain" (`client.py:341-345`, docstring only). Its shape is
  undocumented.
- **No policy field names an approver role.** None of the policy-spec pages document one.

**Experiment:**

1. Call `GET /delegation/my-role` with keys and emails for an Org Admin and a Developer. This
   prints the role names and limits.
2. Call `POST /iap/sdk/resolve-user` for each and inspect the approver chain.
3. Raise a hold as the agent, then approve it as the same user (expect a refusal), as a peer, and
   as an admin. Record each result.

### Q8. Hackathon account: is everything available at no cost?

**Verdict: UNKNOWN. The pricing page is login-gated, and the documented quotas may bite.**

- The only plan text in the docs covers ArmorIQ Tools, not the platform:
  > "**Billing.** Settings → Billing is real: Free and Pro [...]. Pro is **$9 a month or $90 a
  > year**, flat, no per-call overage."

  ([/tools/limits](https://docs.armoriq.ai/tools/limits)). No feature split is listed.
- `armoriq.ai/pricing` returns 404. The console `/pricing` routes are empty SPA shells until
  sign-in.
- **Default org quotas on the platform:** Team Members 5, MCP Servers 2, Agents 4, Proxy Servers 2,
  **Policies 2**, API Keys 10. "Contact ArmorIQ support to increase quotas"
  ([/platform/organizations/roles-quotas](https://docs.armoriq.ai/platform/organizations/roles-quotas)).
- Two policies may be too few if we want separate policies per tool group. One policy with several
  `memberRules` and `toolEnforcement` entries probably fits.
- No doc says policies, holds, delegation or observability are paywalled.
- Observability is on by default for SDK sessions, with 30-day retention
  ([/platform/observability](https://docs.armoriq.ai/platform/observability)).

**Experiment:**

1. Sign in to both consoles and screenshot Settings → Billing and Roles & Quotas.
2. Try creating a third policy.
3. Ask the organizers which product the hackathon "Pro" applies to.

---

## Implications for the bridge

1. **Point the SDK at the production defaults** (`api.armoriq.ai`) with a platform.armoriq.ai key,
   unless the organizers confirm that tools.armoriq.ai is where the judges look. In that case, run
   E2 and set `ARMORIQ_ENV` deliberately. Record the chosen environment in every eval report
   alongside `armoriq_mode`.
2. **Author enforcement policies on platform.armoriq.ai**, as a `Policy` document with
   `memberRules`. tools.armoriq.ai's Policy Studio does not govern `/iap/sdk/enforce`.
3. **Bind one explicit policy** with `defaultEnforcementAction: block` and list every hotel tool.
   Don't depend on the unbound default (Q1).
4. **Name money arguments `amount`, in dollars**, or register `amountUnit: "cents"` on the tool.
   Pair `requireApprovalAbove` with `enforcementAction: hold` (Q4).
5. **Declare every tool in the captured plan**, or the SDK blocks it locally with `tool-not-in-plan`
   before ArmorIQ is asked (`session.py:804-809`).
6. **Treat `enforce-unavailable` as a block.** The SDK already does. Surface it in the dashboard as
   "ArmorIQ unreachable", not as a policy denial.
7. **Keep identity in the bridge.** The bridge also owns `verify_guest` attempt counting (Q5) and
   may need a service email for `for_user` (Q2).
8. **Use one ArmorIQ session per voice call**, and declare every hotel tool in one `start_plan` at
   the start of the call (Q6).
   - Re-planning mid-call clears the declared tools, mints a new token, and drops any pending
     approval.
   - Set `validity_seconds` above the longest expected call; the session default is 3600.
9. **Handle holds without blocking the event loop.**
   - Use the session path (`enforce_sdk` or `dispatch`). A hold returns `action="hold"` with a
     `delegation_id`.
   - The agent tells the guest "a manager needs to approve that", and an asyncio task runs
     `await session.await_approval(delegation_id)`.
   - Never use `invoke_with_policy(wait_for_approval=True)`, because of `time.sleep`.
10. **The approver (`evals/` and the dashboard) must be a second, higher-ranked human account**,
    never the agent's identity (Q7).
    - The proven route is the dashboard's
      `POST /iap/plan/{planId}/update-status {"status":"approved"}` with that user's Bearer JWT and
      `x-organization-id`. So the bridge must expose `planId` alongside `delegation_id`.
    - Whether that flips `/delegation/{id}/status`, and whether the API-key
      `/delegation/approve` works, must be settled live (Q3 experiment) before the approver is
      built.
    - Mind the 30-60/min delegation rate limit and the 5-10/min login limit.
